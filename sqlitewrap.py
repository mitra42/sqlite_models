# encoding: utf-8
import sqlite3
import time  # For sleep
from datetime import datetime

# Referenced externally

class SqliteWrap(object):
    db = None       # Accessable if working single DB

    def __init__(self, databasefile):
        self.databasefile = databasefile
        self.conn = None
        self.isconnected = False

    @classmethod
    def setdb(cls, databasefile):
        """
        Called by applications to set the db pointer used by model.py
        """
        cls.db=cls(databasefile)

    def connect(self):
        """
        Connect to sqlite DB, configure, assign to cherrypy.thread_data
        This is similar to connect_db in utils.py
        """
        self.conn = sqlite3.connect(self.databasefile, detect_types=sqlite3.PARSE_DECLTYPES)
        self.conn.execute('pragma foreign_keys = on')
        # Dont wait for operating system http://www.sqlite.org/pragma.html#pragma_synchronous
        self.conn.execute('pragma synchronous = off')
        self.conn.row_factory = sqlite3.Row
        # self.curs = self.conn.cursor() # Dont create curs, use the conn's execute method
        self.isconnected = True

    def disconnect(self):
        self.conn.commit()
        self.conn.close()
        self.isconnected = False

    def sqlsend(self, sql, values=None, _verbose=False, maxretrytime=60):
        """
        Encapsulate most access to the sql server
        Send a sql string to a server, with values if supplied

        sql: sql statement that may contain usual "?" characters
        _verbose: set to true to print or log sql executed
        values[]: array or list of parameters to sql
        ERR: IntegrityError (FOREIGN KEY constraint failed)
        should catch database is locked errors and delay - may need to catch other errors but watch logs for them
        returns cursor which can be used as an iterator, or queried esp rowcount an lastrowid
        """
        # TODO-LOG - move prints to logs
        retrytime = 0.001  # Start with 1mS, might be far too short
        e = None
        if _verbose:
            print sql, values if values else ""
        while retrytime < maxretrytime:  # Allows up to about 60 seconds of delay - enough for a long OVP generation
            # noinspection PyBroadException,PyBroadException
            try:
                if values is None:
                    return self.conn.execute(sql)
                else:  # values supplied as array
                    return self.conn.execute(sql, values)
            except sqlite3.OperationalError as e:
                if 'database is locked' not in str(e):
                    break  # Drop out of loop and raise error
                print "Waiting for lock", retrytime
                time.sleep(retrytime)
                retrytime *= 2  # Try twice as long each iteration
            except Exception as e:
                break  # Drop out of loop and raise error
        print "SQL FAIL", sql, values if values else ""
        raise e  # This catches any other error

    def sqlfetch(self, sql, values=None, _verbose=False, limit=None):
        """
        Send a sql string to a server, and retrieve results
        sql: sql statement that may contain usual "?" characters
        _verbose: set to true to print or log sql executed - note some functions turn verbose on if cls.debug = True
        values[]: array or list of parameters to sql
        returns iterator (possibly empty) of Rows (each of which behaves like a dict)
        """
        curs = self.sqlsend(sql, values, _verbose=_verbose)
        return curs.fetchmany(limit) if limit else curs.fetchall()

    def sqlfetch1(self, sql, values=None, _verbose=False):
        """
        Send a sql string to a server, and retrieve single result or None
        sql: sql statement that may contain usual "?" characters
        _verbose: set to true to print or log sql executed - note some functions turn verbose on if cls.debug = True
        values[]: array or list of parameters to sql
        returns iterator (possibly empty) of Rows (each of which behaves like a dict)
        """
        return self.sqlsend(sql, values, _verbose=_verbose).fetchone()

