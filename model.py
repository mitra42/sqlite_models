# encoding: utf-8
import sqlite3
from datetime import datetime
from json import loads, dumps
from sqlitewrap import SqliteWrap

# Local files
from model_exceptions import (ModelExceptionRecordNotFound, ModelExceptionUpdateFailure, ModelExceptionInvalidTag,
                              ModelExceptionRecordTooMany, ModelExceptionCantFind)

class Model(object):
    """
    A parent class - subclassed for each type of record in an application

    Concepts supported:

    A record can be *loaded* or not, meaning that its been updated from the database.
    This allows low cost references to objects that are just the unloaded class.
    Note uses "sqlite3.Row" which is the instance returned by iteration of cursor, or fetchone, and looks bit like dict
    Model(int)   Create a placeholder object that can be loaded and refers to a certain id
    Model(row)  Initialise from a row
    _loaded     True if object loaded from database
    load()      Load the object, if not already done so.
    load(row)   Initialize object from a "row"
    insert(**)  Insert an object into the database based on a dict of parameters,
    update(**) Update fields of an object (object and on disk), takes several parameters that modify behavior

    A record may contain boolean fields called "Tags" which are an array of strings stored in the Tags field,

    Most functions return the object, so they can be chained e.g.  foo(3).load().xyz()

    Special fields of the Model Instance
    SQL     FIELD   NOTE
    id      id      Contains the unique id of the record (always accessed via id()
    tags    tags    Contains a list of strings that represent boolean flags
    parms   multiple SQL Contains a json dic of fields that dont have their own column (easy to expand without changing table structure)

    Other Special fields of the Model Class
    _tablename  Name of table stored in

    Administration
    createtable()  Creates a table
    _create


    """
    _tablename = "nosuchtable"
    _lastmodfield = None        # Override to specify where tostore timestamp (usually lastmod)
    _validtags = {}             # No valid tags by default
    _parmfields = ()
    _deletesql = "DELETE FROM %s WHERE id = ?"  # Unlikely to be subclassed
    _supportedclasses = {}

    def __init__(self, row):
        """
        Define an object
        If passed a sqlite3.Row then initialize from that
        If passed an int, then just save the id, and set _loaded=False so will be lazily loaded if reqd
        """
        if isinstance(row, sqlite3.Row):
            self.load(row=row)  # Expands tags etc, Sets _loaded
        elif isinstance(row, (int,basestring)):
            self.id = int(row)
            self._loaded = False
        else:
            assert isinstance(row, int), "Argument to __init__ can only be Row or int, but its " + type(row).__name__

    # Accessing attributes
    def __getattr__(self, name):
        """
        Gets fields of model so can access as e.g. foo = Model(), foo.A
        """
        if not self._loaded:
            self.load()
        return self.__dict__.get(name,None)

    """
    def __setattr__(self, name, value):
        #TODO - may need to do things if set fields and not handled by convertor
        #if name[0] == "_":  # #Write fields starting with _ direct to object e.g. _loaded
            object.__setattr__(self, name, value)
        #else:
        #    print "__setattr__", name, value
    """

    def __unicode__(self):
        """
        Print the object - simplistic, just printing values
        """
        return "%s %s" % (self.__class__.__name__, self.__dict__)

    def __str__(self):
        """
        Subclasses should implement __unicode__ rather than __str__
        See http://stackoverflow.com/questions/1307014/python-str-versus-unicode
        """
        return unicode(self).encode('utf-8')

    def __repr__(self):
        # Returns abbreviated version - most often used inside print of another object
        return "%s(%d)" % (self.__class__.__name__, self.id)

    def __conform__(self, protocol):
        # Turn into a int to store in DB
        if protocol is sqlite3.PrepareProtocol:
            return self.id

    def __eq__(self, other):
        """
        Comparing two models is to compare their id's
        :param other: Model or something can can compare to an int
        :return: True if model id's match or id == other
        """
        if isinstance(other, Model):
            return self.id == other.id
        else:
            return self.id == other     # Defaults to int comparisom depending on class of other

    @classmethod
    def createtable(cls, dropfirst=False):
        """
        Standard creation of table
        relies on a string "_createsql" in each subclass
        """
        if dropfirst:
            SqliteWrap.db.sqlsend("DROP TABLE IF EXISTS " + cls._tablename)
        SqliteWrap.db.sqlsend(cls._createsql % cls._tablename, _verbose=False)

    @classmethod
    def supportedfunction(self, supportedclass, func ):
        """
        :param supportedclass: Class we are checking for support for
        :param func:            Functionality that might be supported
        :return:                function (or lambda) that handles it
        """
        return supportedclass in Model._supportedclasses and Model._supportedclasses[supportedclass].get(func, None)

    def load(self, _verbose=False, row=None):
        """
        Load object if not loaded, return obj so can string together
        If row is set, then will load from row rather than from DB
        Cheap if already loaded
        Calls RecordNotFound which can be subclassed to throw other errors
        """
        if row or not self._loaded: # Need to check row first, or recurses if self._loaded not set (e.g. during init)
            if not row: # We haven't been passed an initialize, so try and load from database
                sql = "SELECT * FROM %s WHERE id = ?" % self._tablename
                row = SqliteWrap.db.sqlfetch1(sql, (self.id,), _verbose=False)
                if row is None:
                    raise ModelExceptionRecordNotFound(table=self._tablename, id=self.id)
            assert isinstance(row, (sqlite3.Row, dict)), \
                "load expects sqlite3.Row but got %s" % type(row).__name__
            for key in row.keys():
                # Note that converting types, such as a model, is done by a converter on each type, not here.
                if key == "tags" and row[key] is None:
                    self.__setattr__(key, Tags())   # Make sure its never None, simplifies operations
                elif key == "parms":
                    if row[key] is not None: # Field specified as JSON, so will be dict by time gets here
                        parmsdic = row[key]
                        for parmskey in parmsdic: #
                            s = parmsdic[parmskey]
                            parmscls=self._parmfields[parmskey]
                            if s is None:   # Catch any None as constructor often wont work on None
                                self.__setattr__(parmskey, None)
                            elif self.supportedfunction(parmscls, "parms2attr"):
                                # Find types stored in a known format
                                # See examples in datetime
                                self.__setattr__(parmskey, self.supportedfunction(parmscls, "parms2attr")(s))
                            else:   # Default to constructor of class (also works with str, unicode, int, float)
                                # Works with subclasses of: Model; Models;
                                self.__setattr__(parmskey, parmscls(s))
                            #SEE OTHER !ADD-TYPE if parmscls() can't handle string as stored in SQL, define as supportedclass
                else:
                    self.__setattr__(key, row[key])
            self._loaded = True
        return self # Allow chaining


    @classmethod
    def insert(cls, _verbose=False, **kwargs):   #TODO-LOG bLog=False, _login=None,
        """
        Standard insert method that uses the insertstr defined in each class
        call this from iinsert(..<class dependent field list>.) in each class
        Note - can pass record as parameters and will auto-convert to id.
        """
        id = SqliteWrap.db.sqlsend(cls._insertsql % cls._tablename, _verbose=_verbose ).lastrowid
        obj = cls(id)
        if cls._lastmodfield:
            kwargs[cls._lastmodfield] = timestamp()
        #TODO-LOG - logging not done
        #if bLog:
        #    from .log import Log
        #    Log.iinsertNew(obj, None, LOGCREATED, 'Created', None, _login,
        #                   None)  # Knows that last field of r always tags string

        #TODO-TYPE Implement type checking, or maybe just in update
        #SEE OTHER !ADD-TYPE
        #for key in kwargs:
        #    for k, err in cls.strfields:
        #        #TODO NEEDS SHOULDBE if key == k: kwargs[k] = shouldbe(kwargs.get(k, None), str, ONEORNONE, err)
        #    for k, err in cls.intfields:
        #        #TODO NEEDS SHOULDBE if key == k: kwargs[k] = shouldbe(kwargs.get(k, None), int, ONEORNONE, err)
        #    for k, err in cls.floatfields:
        #        #TODO NEEDS SHOULDBE  if key == k: kwargs[k] = shouldbe(kwargs.get(k, None), float, ONEORNONE, err)

        obj.update(_skipNone=False, _verbose=_verbose, **kwargs)  # Set if explicitly None, 0 or "" # TODO-LOG _login=_login, bLog=bLog,
        return obj

    def delete(self):
        """
        Delete an object
        """
        SqliteWrap.db.sqlsend(self._deletesql % self._tablename, (self.id,))

    def update(self, _skipNone=False, _lastmod=True, _verbose=False, **kwargs): # _log=True, _login=None,
        """
        Update the record for all (field, newvalue) in kwargs
        Note that kwargs values may be a subclass of Model #TODO-LOG and it should be logged appropriately
        Note that keys and values are guaranteed to be same order, since the dict is not modified in between
        Take care here, because its valid to set tags to None, so absence of kwargs["tags"] is not same as it being None
        Fields in cls._parmfields are handled separately as all need writing to single parms field
        _skipNone = True will cause it NOT to update fields set to None, otherwise it sets them to None
        _lastmod        Will set the _lastmodfield to the current time
        """
        id = self.id
        #classes = {}
        if _skipNone:
            kwargs = {k: v for k, v in kwargs.items() if v}  # Ignore non None
        """
        for k in kwargs.keys():
            if isinstance(kwargs[k], Record):
                classes[k] = kwargs[k].__class__        # TODO-LOG
        """
        logkwargs = kwargs.copy()  # Make a copy - needs to be a copy so can manipulate independently,
        if self._lastmodfield and _lastmod:  # Do this after copying to logkwargs as dont want to log the change to lastmod
            kwargs[self._lastmodfield] = timestamp()
        self.load()         # Make sure loaded locally without the updates
        self.load(row=kwargs)   # Save into local object - will also update any parms or tags fields
        # Second round of manipulating kwargs AFTER set into object
        # - parmfields stripped out in keys= below

        keys = [ k for k in kwargs if k not in self._parmfields ]   # Strip out parmfields and send full string
        values = [ kwargs[k] for k in keys ]
        #print "XXX@266",keys,values,values[0].__class__.__name__ if values else None
        if any([k in self._parmfields for k in kwargs]):   # Are there any tag from parmfields (Note kwargs unchanged at this point)
            keys.append("parms")
            values.append(self.parms())                     # self.parms() handles conversion of different types of parms

        field_update = ", ".join("%s = ?" % k for k in keys)
        # noinspection PyTypeChecker
        where, ids = self.sqlpair("id", id)
        updatesql = "UPDATE %s SET %s WHERE %s" % (self._tablename, field_update, where)
        values = values + ids
        rowcount = SqliteWrap.db.sqlsend(updatesql, values, _verbose=False).rowcount
        if rowcount > 0:
            pass
            """TODO-LOG
            if bLog:
                ## Avoid cyclic dependencies
                from .log import Log
                # logstr = "updated fields: %s" % (', '.join(
                #   ['%s to %s' % (k, v) for k, v in kwargs.items()]))
                if isinstance(id, int):
                    id = [id]
                for i in id:
                    for k in logkwargs:
                        if k in ("chipid", "password"):
                            v = "*hidden*"
                        else:
                            v = logkwargs[k]
                        if classes.get(k, None):
                            Log.iinsert(cls, i, classes.get(k, None), v, LOGSET, u"update field:" + k, None, _login)
                        elif isinstance(v, int):
                            Log.iinsert(cls, i, None, v, LOGSET, u"update field:" + k, None, _login)
                        else:
                            Log.iinsert(cls, i, None, None, LOGSET, u"update field:%s=%s" % (k, repr(v)), None, _login)
            """
        else:
            raise ModelExceptionUpdateFailure(sql=updatesql, valuestring=str(values))
        return logkwargs  # For reporting to user

    @classmethod
    def find(cls, _skipNone=False, _verbose=False, _nullerr=None, _manyerr=ModelExceptionRecordTooMany, **kwargs):
        """
        Do a SQL SELECT and return all results, see sqlpair for documentation of special arguments
        _skipnone   True if should ignore arguments that are None
        _nullerr    Set to exception if should raise an error on failure, typically ModelExceptionRecordNotFound
        _manyerr    Error to return if more than one (set to None to always return first item found), defaults ModelExceptionRecordTooMany
        Returns a single record
        See Models.find if want a list returned
        """
        keys, val1 = zip(
            *[cls.sqlpair(key, val) for key, val in kwargs.iteritems() if not (_skipNone and val is None)])
        vals = flatten2d(val1)
        sql = "SELECT * FROM %s WHERE %s" % (cls._tablename, " AND ".join(keys))
        rr = SqliteWrap.db.sqlfetch(sql, vals, _verbose=_verbose)
        if len(rr) > 1 and _manyerr:
            raise _manyerr(table=cls._tablename, where=unicode(**kwargs))
        elif len(rr) == 0:
            if _nullerr:
                raise _nullerr(table=cls._tablename, where=unicode(kwargs))
            else:
                return None
        else:
             return cls(rr[0])

    @classmethod
    def sqlpair(cls, key, val):
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
        if key == "tags":
            return key + " LIKE ?", ["%'" + val + "'%"]
        # SEE OTHER !ADD-TYPE - check for type in both parmfields and non-parmfields,
        if key not in cls._parmfields:
            # Note this next one is problematic since sqlite3 bug with list as a parameter and cant pass as string or tuple either
            if isinstance(val, (tuple, list, set)):  # Also handles Models
                return key + " IN (" + ','.join(['?'] * len(val)) + ")", [v.id if isinstance(v, Model) else v for v
                                                                          in
                                                                          val]
            if val is None:
                return key + " IS NULL", []  # XXX Note this will fail (Operational Error) if val is None but key is in parmfields
            if isinstance(val, Model):
                return key + " = ?", [val.id]  # Note not in parmfields as pulled out above
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
            if cls.supportedfunction(val.__class__,"attr2parms"):
                return "parms LIKE ?", ['%"' + key + '": ' + cls.supportedfunction(val.__class__,"attr2parms")(val) + '%']
            if isinstance(val, (int, float)):
                # This is really not an efficient search, and prone to error if not encoded exactly if often used then move field from parms to main field
                return "parms LIKE ?", ['%"' + key + '": ' + unicode(val) + '%']
            assert False, ("Syntax unsupported", key, val)

    # ========== TAGS ==(see also Tags class) ========================================
    def hastag(self, tag): return tag in self.tags

    def settags(self, newtags):
        # Note sideeffect of self.tags.copy is to load if not already loaded
        oldtags = self.tags.copy()  # Have to copy as otherwise its a pointer to self.tags which changes
        self.tags.settags(newtags, model=self)       # Add tag or iterable
        if oldtags != self.tags:
            self.update(tags=self.tags)   # Save  #TODO-AUTOSAVE check if needed after have auto-saving

    def cleartags(self, tags):
        # Note sideeffect of self.tags.copy is to load if not already loaded
        oldtags = self.tags.copy()  # Have to copy as otherwise its a pointer to self.tags which changes
        self.tags.cleartags(tags)
        if oldtags != self.tags:
            self.update(tags=self.tags)   # Save #TODO-AUTOSAVE check if needed after have auto-saving

    def hasanytags(self, tags):
        return self.tags.hasanytags(tags)

    # =========== HANDLING parms field ==============
    def forparms(self, name):
        # Convert parameter for storing in parms
        val = self.__getattr__(name)
        if self.supportedfunction(val.__class__,"attr2parms"):
            # Support extension types that define a way to write to parms
            return self.supportedfunction(val.__class__,"attr2parms")(val)
        elif isinstance(val, Model):
            return val.id
        elif isinstance(val, Models):
            return [m.id for m in val]  # Store as list of ids
        else:
            return val
        #SEE OTHER !ADD-TYPE, may need to convert type to string for storage if cant use automatic json conversion

    def parms(self):
        # Build a dictionary from all the fields saved in the parms field
        return { k: self.forparms(k) for k in self._parmfields}

    @classmethod
    def add_supportedclass(self, newclass, **kwargs):
        Model._supportedclasses[newclass] = kwargs

# This is an example of adding support for the datetime class (See !ADD-TYPE)
Model.add_supportedclass(datetime,
               parms2attr=lambda s: datetime.strptime(s, "%Y-%m-%dT%H:%M:%S.%f"),
               attr2parms=datetime.isoformat, # Convert a datetime to a storable string
               )

class Tags(set):
    #def adapt_tags(self):
    #   return dumps(list(self))

    def __conform__(self, protocol):
        # Turn into a json string to store in DB
        if protocol is sqlite3.PrepareProtocol:
            return dumps(list(self))

    def settags(self, other, model=None):
        """
        Add to the tags
        :param other: string or iterable
        :return: None
        """
        if other is None:
            return self
        if isinstance(other, basestring):
            other = {other}
        if model and model._validtags and not model._validtags.issuperset(other):
            raise ModelExceptionInvalidTag(table=model._tablename, validtags=model._validtags, tags=other)
        return self.update(other)   # Note Returns None, not list of new tags

    def cleartags(self, other):
        """
        Add to the tags
        :param other: string or iterable
        :return: None
        """
        if other is None:
            return self
        elif isinstance(other, basestring):
            return self.difference_update({other})  # Note Returns None, not list of new tags
        else:
            return self.difference_update(other)  # Note Returns None, not list of new tags

    def hasanytags(self, other):
        if other is None:
            return False
        elif isinstance(other, basestring):
            return other in self  # Note Returns None, not list of new tags
        else:
            return bool(self.intersection(other))  # Note Returns None, not list of new tags

def convert_tags(s):
    # Note s is never None or Null etc, that skips the conversion and returns None
    return Tags(loads(s))

sqlite3.register_converter("tags", convert_tags)  # Return JSON, could be dict or list

    # ========== JSON OTHER ================================

sqlite3.register_adapter(dict, dumps)
sqlite3.register_adapter(list, dumps)   # Note this also covers Models which is a list
sqlite3.register_adapter(tuple, dumps)   # Note this also covers Models which is a list
sqlite3.register_converter("json", loads)  # Return JSON, could be dict or list

class Models(list):
    """
    Handle ordered list of Model - all of same class
    adapter is covered by
    """
    _singular = Model    # Subclass this to be the singular class
    _selectallsql = "SELECT * FROM %s"
    _parmfields = []


    def __init__(self, ll):
        """
        Initialize an array of Models
        :param ll: iterator that returns a valid arg to the ModelXyz() esp int or sqlite3.Row or single item
        """
        if not isinstance(ll, (list, tuple, set)):
            ll = [ ll]
        super(Models, self).__init__([(l if isinstance(l, Model) else self._singular(l)) for l in ll ])


    def __conform__(self, protocol):
        # Turn into a int to store in DB
        if protocol is sqlite3.PrepareProtocol:
            return dumps([ l.id for l in self ])

    def contains(self, other):
        return other in self

    def set(self):
        """
        Only return new examples
        """
        rro = []
        for r in self:
            if r not in rro:
                rro.append(r)
        return self.__class__(rro)

    @classmethod
    def all(cls):
        """
        :return: list of all objects
        """
        return cls(SqliteWrap.db.sqlfetch(cls._selectallsql % cls._singular._tablename))

    @classmethod
    def find(cls, _skipNone=False, _verbose=False, **kwargs):
        """
        Do a SQL SELECT and return all results, see sqlpair for documentation of special arguments
        _skipnone   True if should ignore arguments that are None
        Returns a list which may be empty
        See Model.find if want a single item returned
        """
        keys, val1 = zip(
            *[cls._singular.sqlpair(key, val) for key, val in kwargs.iteritems() if not (_skipNone and val is None)])
        vals = flatten2d(val1)
        sql = "SELECT * FROM %s WHERE %s" % (cls._singular._tablename, " AND ".join(keys))
        return cls(SqliteWrap.db.sqlfetch(sql, vals, _verbose=_verbose))

    def update(self, _skipNone=False, _lastmod=True, _verbose=False, **kwargs): # _log=True, _login=None,
        # Fairly inefficient update as has to load each one first
        for m in self:
            m.update(_skipNone=_skipNone, _lastmod=_lastmod, _verbose=_verbose, **kwargs)


def timestamp():
    """ Seperated out as sometimes implemented as timestamp of the query"""
    return datetime.now()

def flatten2d(rr):
    return [ leaf for tree in rr for leaf in tree ]  # Super obscure but works and fast
    # See  http://stackoverflow.com/questions/952914/making-a-flat-list-out-of-list-of-lists-in-python/952952#952952

