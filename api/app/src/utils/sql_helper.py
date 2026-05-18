import pandas as pd
import json
from sqlalchemy import text, MetaData, Table
from typing import List, Dict, Union

from src.context import Context
from src.utils.timing import timing


class SqlHelper:

    def __init__(
        self,
        context: Context,
    ):
        self._context = context
        self._log = context.log

        with self._context.db_con.connect() as conn:
            self.db_tables = pd.read_sql(
                "SELECT table_name FROM information_schema.tables",
                con=conn.connection,  # needed for DAG working airflow
            )
        self.db_tables = self.db_tables["table_name"].tolist()

    def read_sql_data(self, table_name, params=None):
        try:
            with self._context.db_con.connect() as conn:
                return pd.read_sql(table_name, con=conn.connection, params=params)
        except Exception as e:
            raise Exception(f"table name does not exist in SQL : {table_name}", e)

    def get_table_rows_count(self, table_name):
        with self._context.db_con.connect() as conn:
            return pd.read_sql(
                f'SELECT COUNT(*) FROM "{table_name}"', con=conn.connection
            )["count"].values[0]

    def get_table_cols_count(self, table_name):
        with self._context.db_con.connect() as conn:
            return pd.read_sql(
                f"SELECT * FROM information_schema.columns WHERE table_name = '{table_name}'",
                con=conn.connection,
            ).shape[0]

    def drop_table(self, table_name):
        with self._context.db_con.connect() as conn:
            conn.execute(text(f'DROP TABLE "{table_name}"'))

    def write_to_sql(self, dataframe, table_name, if_exists="append"):
        with self._context.db_con.connect() as conn:
            dataframe.to_sql(
                name=table_name,
                con=conn.connection,
                if_exists=if_exists,
                chunksize=50000,
                index=False,
            )

    @timing
    def write_sql_data(self, dataframe, table_name, if_exists=None):
        if table_name in self.db_tables:
            col_count = self.get_table_cols_count(table_name)
            row_count = self.get_table_rows_count(table_name)

            if if_exists:
                self._log.info(
                    f"TABLE EXISTS AND WILL BE {if_exists.upper()} INTO SQL : {table_name} ......"
                )
                self.write_to_sql(dataframe, table_name, if_exists=if_exists)
                self._log.info(f"WRITTEN INTO SQL : {table_name}")
            else:
                if dataframe.shape[1] != col_count:
                    self._log.info(
                        f"{table_name} - WILL BE DELETED TO ADD {col_count - dataframe.shape[1]} new columns"
                    )
                    self.write_to_sql(dataframe, table_name, if_exists="replace")
                    self._log.info(f"WRITTEN INTO SQL : {table_name}")
                elif dataframe.shape[0] > row_count:
                    self._log.info(
                        f"INSERT {row_count - dataframe.shape[0]} NEW OBSERVATIONS TO {table_name}"
                    )
                    self.write_to_sql(dataframe, table_name)
                    self._log.info(f"WRITTEN INTO SQL : {table_name}")
                else:
                    self._log.info(f"DATA {table_name} IS ALREADY UP TO DATE")
        else:
            self._log.info(f"WRITTING INTO SQL : {table_name} ......")
            self.write_to_sql(dataframe, table_name)
            self._log.info(f"WRITTEN INTO SQL : {table_name}")

    @timing
    def remove_rows_sql_data(self, values, column, table_name):

        if any(char.isupper() for char in table_name):
            quoted_table_name = f'"{table_name}"'
        else:
            quoted_table_name = table_name

        if table_name in self.db_tables:
            str_values = ", ".join([f"'{x}'" for x in values])
            with self._context.db_con.connect() as conn:
                conn.execute(
                    text(
                        f"""DELETE FROM {quoted_table_name}
                            WHERE {column} IN ({str_values}) """
                    )
                )
            self._log.info(f"REMOVED {len(values)} OBS FROM TABLE {quoted_table_name}")
        else:
            self._log.warning(f"{quoted_table_name} does not exist in the Database")

    def insert_raw_to_table(
        self,
        unique_id_col: Union[str, list],
        row_dict: Dict,
        table_name: str,
        do_replace=True,
    ):

        if isinstance(unique_id_col, str):
            list_unique_id_col = [unique_id_col]
        elif isinstance(unique_id_col, list):
            list_unique_id_col = unique_id_col
        else:
            raise Exception(
                f"Please ensure unique id col is string or list, got {type(unique_id_col)}"
            )

        if table_name in self.db_tables:

            if any(char.isupper() for char in table_name):
                quoted_table_name = f'"{table_name}"'
            else:
                quoted_table_name = table_name

            # Serialize dict values to JSON strings
            for key, value in row_dict.items():
                if isinstance(value, dict):
                    try:
                        row_dict[key] = json.dumps(value)
                    except Exception:
                        row_dict[key] = None

            keys_to_string = ", ".join([f'"{x}"' for x in row_dict.keys()])
            placeholders = ", ".join([":{}".format(col) for col in row_dict.keys()])
            update_columns = ", ".join(
                [
                    (f""""{k}" = :{k} """)
                    for k, _ in list(row_dict.items())
                    if k not in list_unique_id_col
                ]
            )

            if do_replace:
                conflict_columns = ", ".join([f'"{col}"' for col in list_unique_id_col])
                query = f"""INSERT INTO {quoted_table_name} ({keys_to_string})
                            VALUES ({placeholders})
                            ON CONFLICT ({conflict_columns})
                            DO UPDATE
                            SET {update_columns} ;"""
            else:
                query = f"""INSERT INTO {quoted_table_name} ({keys_to_string})
                             VALUES ({placeholders})"""

            with self._context.db_con.begin() as conn:
                try:
                    conn.execute(text(query), row_dict)

                except Exception as e:
                    if "value violates unique constraint" in str(e):
                        self._log.warning(
                            f"Row already saved in db {quoted_table_name}"
                        )
                    else:
                        self._log.error(f"Something wrong happened {e} \\ {query}")
                finally:
                    pass

    def insert_many_to_table(
        self,
        unique_id_col: Union[str, list],
        rows: List[Dict],
        table_name: str,
        do_replace: bool = True,
    ):
        """
        Efficiently inserts multiple dictionary rows into a specified database table.

        This method uses the `executemany` pattern for high performance by sending
        all data to the database in a single round trip.

        Args:
            unique_id_col: The column or list of columns that form the unique constraint.
            rows: A list of dictionaries, where each dictionary represents a row.
            table_name: The name of the target database table.
            do_replace: If True, performs an "upsert" using ON CONFLICT...DO UPDATE.
                        If False, performs a simple INSERT.
        """
        if not rows:
            self._log.info("No rows provided to insert_many_to_table. Skipping.")
            return

        # 1. Normalize unique_id_col to be a list (same as original)
        if isinstance(unique_id_col, str):
            list_unique_id_col = [unique_id_col]
        elif isinstance(unique_id_col, list):
            list_unique_id_col = unique_id_col
        else:
            raise TypeError(
                f"Please ensure unique id col is a string or list, got {type(unique_id_col)}"
            )

        quoted_table_name = (
            f'"{table_name}"'
            if any(char.isupper() for char in table_name)
            else table_name
        )

        # 3. Serialize any dict values to JSON strings for all rows
        processed_rows = []
        for row_dict in rows:
            processed_row = row_dict.copy()
            for key, value in processed_row.items():
                if isinstance(value, dict):
                    processed_row[key] = json.dumps(value)
            processed_rows.append(processed_row)

        # 4. Build the SQL query using the keys from the *first* row as a template
        # This assumes all dicts in the list have the same structure.
        first_row_keys = processed_rows[0].keys()
        keys_to_string = ", ".join([f'"{x}"' for x in first_row_keys])
        placeholders = ", ".join([f":{col}" for col in first_row_keys])

        update_columns = ", ".join(
            [
                # Use EXCLUDED to refer to the values proposed for insertion
                (f'"{k}" = EXCLUDED."{k}"')
                for k in first_row_keys
                if k not in list_unique_id_col
            ]
        )

        # 5. Construct the final query with or without the ON CONFLICT clause
        if do_replace and update_columns:
            conflict_columns = ", ".join([f'"{col}"' for col in list_unique_id_col])
            query = f"""INSERT INTO {quoted_table_name} ({keys_to_string})
                        VALUES ({placeholders})
                        ON CONFLICT ({conflict_columns})
                        DO UPDATE SET {update_columns};"""
        else:
            query = f"""INSERT INTO {quoted_table_name} ({keys_to_string})
                        VALUES ({placeholders});"""

        # 6. Execute the query with the list of processed rows
        with self._context.db_con.begin() as conn:
            try:
                # SQLAlchemy's execute method with a list of dicts performs a bulk insert (executemany)
                conn.execute(text(query), processed_rows)
                self._log.info(
                    f"Successfully inserted/updated {len(processed_rows)} rows in {quoted_table_name}."
                )
            except Exception as e:
                # A general error is more likely in a bulk operation than a specific unique violation
                self._log.error(f"DB Error on bulk insert: {e} \\ Query: {query}")

    def update_raw_to_table(self, query, params=None):
        with self._context.db_con.begin() as conn:
            try:
                if not params:
                    conn.execute(text(query))
                if params:
                    conn.execute(text(query), params)
            except Exception as e:
                self._log.error(f"Something wrong happened {e}")
            finally:
                pass

    @timing
    def create_table_if_not_exist(self, table_name, columns):
        metadata = MetaData()
        _ = Table(table_name, metadata, *columns)
        metadata.create_all(self._context.db_con)
