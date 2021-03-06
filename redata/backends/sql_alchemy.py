from redata.backends.base import DB
from sqlalchemy import select, Interval, func, text, cast, Date, distinct, desc
from sqlalchemy.schema import MetaData
from datetime import datetime, timedelta

class SqlAlchemy(DB):

    def __init__(self, name, db, schema=None):
        super().__init__(name, db, schema)

    def get_table_obj(self, table):
        if not getattr(self, '_per_namespace', None):
            self._per_namespace = {}
            for namespace in self.namespaces:
                metadata = MetaData(schema=namespace)	
                metadata.reflect(bind=self.db)
                self._per_namespace[namespace] = metadata

        return self._per_namespace[table.namespace].tables[table.full_table_name]

    def table_names(self, namespace):
        return self.db.table_names(namespace)

    def filtered_by_time(self, stmt, table, interval, conf):
        q_table = self.get_table_obj(table)

        start = self.get_time_to_compare(interval, conf.for_time)
        stop = self.get_timestamp(conf.for_time)

        stmt = stmt.where(
            (q_table.c[table.time_column] > start) &
            (q_table.c[table.time_column] < stop)
        )
        return stmt

    def check_data_volume(self, table, time_interval, conf):
        q_table = self.get_table_obj(table)
        stmt = select([func.count().label('count')]).select_from(q_table)

        stmt = self.filtered_by_time(stmt, table, time_interval, conf)
        result = self.db.execute(stmt).first()

        return result

    def get_timestamp(self, from_time):
        return from_time

    def to_naive_timestamp(self, from_time):
        return from_time

    def get_time_to_compare(self, time_interval, for_time):
        before = self.transform_by_interval(time_interval, for_time)
        return before

    def transform_by_interval(self, time_interval, for_time):
        parts = time_interval.split(' ')
        if parts[-1] == 'day':
            to_compare = for_time - timedelta(days=int(parts[0]))
        if parts[-1] == 'hour':
            to_compare = for_time - timedelta(hours=int(parts[0]))
        return to_compare
    
    def check_data_volume_diff(self, table, from_time, conf):
        q_table = self.get_table_obj(table)

        start = self.get_timestamp(from_time)
        stop = self.get_timestamp(conf.for_time)
        casted_date = cast(q_table.c[table.time_column], Date)

        stmt = select([
            casted_date.label('date'),
            func.count().label('count')
        ]).select_from(q_table)

        stmt = stmt.where(
            (q_table.c[table.time_column] > start) &
            (q_table.c[table.time_column] < stop)
        )

        stmt = stmt.group_by(casted_date)

        result = self.db.execute(stmt).fetchall()
        
        return result
    
    def check_data_delayed(self, table, conf):

        q_table = self.get_table_obj(table)

        stmt = select([
            func.max(q_table.c[table.time_column
        ]).label('max_time')]).select_from(q_table)

        stmt = stmt.where(q_table.c[table.time_column] < self.get_timestamp(conf.for_time))

        result = self.db.execute(stmt).first()

        if result[0] is None:
            return [None]
        
        result_time = self.to_naive_timestamp(result.max_time)

        return [conf.for_time - result_time]


    def check_generic(self, func_name, table, checked_column, time_interval, conf):
        q_table = self.get_table_obj(table)

        fun = getattr(func, func_name)

        stmt = select([
            fun(q_table.c[checked_column]).label('value')
        ]).select_from(q_table)
        
        stmt = self.filtered_by_time(stmt, table, time_interval, conf)

        result = self.db.execute(stmt).first()

        return result

    def check_count_nulls(self, table, checked_column, time_interval, conf):
        q_table = self.get_table_obj(table)
        stmt = select([func.count().label('value')]).select_from(q_table)

        stmt = stmt.where((q_table.c[checked_column] == None))

        stmt = self.filtered_by_time(stmt, table, time_interval, conf)

        result = self.db.execute(stmt).first()

        return result


    def check_count_per_value(self, table, checked_column, time_interval, conf):

        q_table = self.get_table_obj(table)

        column = q_table.c[checked_column]

        stmt = select([
            func.count(distinct(column)).label('count')
        ]).select_from(q_table)

        stmt = self.filtered_by_time(stmt, table, time_interval, conf)

        result = self.db.execute(stmt).first()

        if result.count > 10:
            return None
        
        stmt = select([
            func.count().label('count'),
            (column).label('value')
        ]).select_from(q_table)

        stmt = self.filtered_by_time(stmt, table, time_interval, conf)
        stmt = stmt.where((column != None))
        
        stmt = stmt.group_by(column).order_by(desc('count')).limit(10)

        result = self.db.execute(stmt).fetchall()

        return result

    def get_table_schema(self, table_name, namespace):
        schema_check = f"and table_schema = '{namespace}'" if namespace else ''
        result = self.db.execute(f"""
            SELECT 
                column_name, 
                data_type 
            FROM 
                information_schema.columns
            WHERE 
                table_name = '{table_name}'
                {schema_check}
        """)
        
        return [ {'name': c_name, 'type': c_type} for c_name, c_type in result]
