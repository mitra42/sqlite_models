# encoding: utf-8
import sqlite3
import time  # For sleep
from datetime import datetime



class SqliteWrap(object):
    def __init__(self, databasefile):
        self.databasefile = databasefile
        self.conn = None
        self.isconnected = False

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

    def sqlsend(self, sql, values=None, verbose=False, maxretrytime=60):
        """
        Encapsulate most access to the sql server
        Send a sql string to a server, with values if supplied

        sql: sql statement that may contain usual "?" characters
        verbose: set to true to print or log sql executed
        values[]: array or list of parameters to sql
        ERR: IntegrityError (FOREIGN KEY constraint failed)
        should catch database is locked errors and delay - may need to catch other errors but watch logs for them
        returns cursor which can be used as an iterator, or queried esp rowcount an lastrowid
        """
        # TODO-LOG - move prints to logs
        retrytime = 0.001  # Start with 1mS, might be far too short
        e = None
        if verbose:
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

    def sqlfetch(self, sql, values=None, verbose=False, limit=None):
        """
        Send a sql string to a server, and retrieve results
        sql: sql statement that may contain usual "?" characters
        verbose: set to true to print or log sql executed - note some functions turn verbose on if cls.debug = True
        values[]: array or list of parameters to sql
        returns iterator (possibly empty) of Rows (each of which behaves like a dict)
        """
        curs = self.sqlsend(sql, values, verbose=verbose)
        return curs.fetchmany(limit) if limit else curs.fetchall()

    def sqlfetch1(self, sql, values=None, verbose=False):
        """
        Send a sql string to a server, and retrieve single result or None
        sql: sql statement that may contain usual "?" characters
        verbose: set to true to print or log sql executed - note some functions turn verbose on if cls.debug = True
        values[]: array or list of parameters to sql
        returns iterator (possibly empty) of Rows (each of which behaves like a dict)
        """
        return self.sqlsend(sql, values, verbose=verbose).fetchone()

    @classmethod
    def sqlpair(cls, key, val, parmfields=None):
        """
        Return a pair of key and value that depends on the type of val and key, suitable for using in a query
        Note this is used for the WHERE clause of both SELECT and UPDATE
        parmfields should be specified if its possible the key could be in parmfields (e.g. in Record.find)
        Supports val's like:
        lists,tuples,sets,Models   -> converted to "IN"    (won't work on parm fields)
        None                -> IS NULL  (won't work on parm fields)
        Model               -> id   ( inefficient on parm fields)
        %string%            -> LIKE ( inefficient on parm fields)
        >|<|>=|<=|!=|<> 123 -> operator 123  (doesn't work on parm fields)
        """
        from model import Model
        if parmfields is None:
            parmfields = []
        # from models.record import Record
        # TODO - handle Value via the converters https://docs.python.org/2/library/sqlite3.html
        # from models.unit import Value
        # TODO include if needed# from misc.jsonextended import JSONtoSqlText
        if key == "tags":
            return key + " LIKE ?", ["%'" + val + "'%"]
        # SEE OTHER !ADD-TYPE - check for type in both parmfields and non-parmfields,
        if key not in parmfields:
            # Note this next one is problematic since sqlite3 bug with list as a parameter and cant pass as string or tuple either
            if isinstance(val, (tuple, list, set)):  # Also handles Models
                return key + " IN (" + ','.join(['?'] * len(val)) + ")", [v.id if isinstance(v, Model) else v for v in
                                                                          val]
            if val is None:
                return key + " IS NULL", []  # XXX Note this will fail (Operational Error) if val is None but key is in parmfields
            if isinstance(val, Model):
                return key + " = ?", [val.id()]  # Note not in parmfields as pulled out above
            if isinstance(val, basestring) and len(val) >= 3 and val[0] == '%' and val[-1] == '%':
                return key + " LIKE ?", [val]
            if isinstance(val, basestring):
                ww = val.split(None, 1)
                if len(ww) > 1 and ww[0] in ('>', '<', '>=', '<=', '!=', '<>'):
                    return key + " " + ww[0] + " ?", [ww[1]]
                    # Drop thru and check as string or int
            return key + " = ?", [val]
        else:  # key is in parmfields
            if isinstance(val, (basestring,)):
                return "parms LIKE ?", [
                    '%"' + key + '": "' + val + '"%']  # this is really not an efficient search, if often used then move field from parms to main field
            if isinstance(val, Model):
                return "parms LIKE ?", ['%"' + key + '": ' + unicode(val.id()) + '%']
            if isinstance(val, (datetime,)):  # Will only get exact times, not same day or same minute
                return "parms LIKE ?", ['%"' + key + '": ' + val.isoformat() + '%']
            if isinstance(val, (int, float)):
                # This is really not an efficient search, and prone to error if not encoded exactly if often used then move field from parms to main field
                return "parms LIKE ?", ['%"' + key + '": ' + unicode(val) + '%']
            # if isinstance(val, (Value,)): #TODO-TYPE support Value in parmfields
            #    val = JSONtoSqlText().encode((val.dd(), val.unit(ONLYONE).id()))  # See matching code in record.py:parms2sql
            #    return "parms LIKE ?", ['%"' + key + '": ' + unicode(val) + '%']
            assert False, ("Syntax unsupported", key, val)
