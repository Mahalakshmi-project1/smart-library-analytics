import mysql.connector

from config import DB_HOST, DB_NAME, DB_PASSWORD, DB_PORT, DB_SSL_CA, DB_USER


def _connection_args():
    args = {"host": DB_HOST, "port": DB_PORT, "user": DB_USER, "password": DB_PASSWORD}
    if DB_SSL_CA:                      # verify the server certificate when a CA file is given
        args["ssl_ca"] = DB_SSL_CA
    return args


def get_db_connection():
    """Open a new MySQL connection (autocommit is OFF: callers commit/rollback).
    TLS is negotiated automatically when the server supports it (cloud MySQL requires it)."""
    return mysql.connector.connect(database=DB_NAME, buffered=True, **_connection_args())


def get_server_connection():
    """Connection without a default database (used by init_db.py to create it)."""
    return mysql.connector.connect(**_connection_args())
