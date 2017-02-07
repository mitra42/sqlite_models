# encoding: utf-8
import sqlite3
from json import loads, dumps
from datetime import datetime
from sqlitewrap import SqliteWrap

# Local files
from model_exceptions import (ModelExceptionRecordNotFound, ModelExceptionUpdateFailure, ModelExceptionInvalidTag,
                              ModelExceptionRecordTooMany)

"""
GOALS
 - open source sqlite wrapper
 - Simpler than Django, ideally single file
 - Packagable
 - Good interaction with data types like "Value", and way to extend it
 - Support for common Python types like Decimal
 - Compatible with running under cherrypy, but not dependent on it.
 - Easy to add support for other types (TODO -document)
"""

"""
CHANGES
    - From 2016 version
    - - dont use nullbehavior etc, use a triple - class, zero, array
    - fields accessed via __getattr__ and __setattr__ rather than needing named functions
    id() -> id
    A.sameAs(B) =>  A == B
    typetable => _tablename
    create => _createsql
    iinsertD => insert
    updateFields => update
    Tags is a class now (subclass of dict)
    update works locally as well as onto disk, so don't have to reload after make changes
    Doesnt use recopy, use "ALTER", recopy was only needed because of constraints (DONT USE CONSTRAINTS)
"""


"""
TODO
Think about auto-saving
TODO-VALUE
find <<TESTING
Think about how to register a new type e.g. Decimal or Value
"""

"""
LEARN
row_factory
cursor - maybe create, and return cursor as result of find
register_converter and register_adapter e.g. fro Value<>str or converter functions https://docs.python.org/2/library/sqlite3.html
"""

db = None

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
            db.sqlsend("DROP TABLE IF EXISTS " + cls._tablename)
        db.sqlsend(cls._createsql, verbose=False)

    def load(self, verbose=False, row=None):
        """
        Load object if not loaded, return obj so can string together
        If row is set, then will load from row rather than from DB
        Cheap if already loaded
        Calls RecordNotFound which can be subclassed to throw other errors
        """
        if row or not self._loaded: # Need to check row first, or recurses if self._loaded not set (e.g. during init)
            if not row: # We haven't been passed an initialize, so try and load from database
                sql = "SELECT * FROM %s WHERE id = ?" % self._tablename
                row = db.sqlfetch1(sql, (self.id,), verbose=False)
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
                            elif parmscls in (datetime,): # Special case time stored in known format
                                self.__setattr__(parmskey, parmscls.strptime(s, "%Y-%m-%dT%H:%M:%S.%f"))
                            else:   # Default to constructor of class (also works with str, unicode, int, float)
                                # Works with subclasses of: Model; Models;
                                self.__setattr__(parmskey, parmscls(s))
                            #SEE OTHER !ADD-TYPE if parmscls() can't handle string as stored in SQL
                else:
                    self.__setattr__(key, row[key])
            self._loaded = True
        return self # Allow chaining


    @classmethod
    def insert(cls,  **kwargs):   #TODO-LOG bLog=False, _login=None,
        """
        Standard insert method that uses the insertstr defined in each class
        call this from iinsert(..<class dependent field list>.) in each class
        Note - can pass record as parameters and will auto-convert to id.
        """
        id = db.sqlsend(cls._insertsql).lastrowid
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

        obj.update(_skipNone=False,  **kwargs)  # Set if explicitly None, 0 or "" # TODO-LOG _login=_login, bLog=bLog,
        return obj

    def delete(self):
        """
        Delete an object
        """
        db.sqlsend(self._deletesql % self._tablename, (self.id,))

    def update(self, _skipNone=False, _lastmod=True, **kwargs): # _log=True, _login=None,
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
        where, ids = SqliteWrap.sqlpair("id", id)
        updatesql = "UPDATE %s SET %s WHERE %s" % (self._tablename, field_update, where)
        values = values + ids
        rowcount = db.sqlsend(updatesql, values, verbose=False).rowcount
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
            raise ModelExceptionUpdateFailure(sql=updatesql, valuestr=str(values))
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
            *[SqliteWrap.sqlpair(key, val, parmfields=cls._parmfields) for key, val in kwargs.iteritems() if not (_skipNone and val is None)])
        vals = flatten2d(val1)
        sql = "SELECT * FROM %s WHERE %s" % (cls._tablename, " AND ".join(keys))
        rr = db.sqlfetch(sql, vals, verbose=_verbose)
        if len(rr) > 1 and _manyerr:
            raise _manyerr(table=cls._tablename, where=unicode(**kwargs))
        elif len(rr) == 0:
            if _nullerr:
                raise _nullerr(table=cls._tablename, where=unicode(**kwargs))
            else:
                return None
        else:
             return cls(rr[0])

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
        if isinstance(val, Model):
            return val.id
        elif isinstance(val, (datetime,)):
            return val.isoformat()
        elif isinstance(val, Models):
            return [m.id for m in val]  # Store as list of ids
        else:
            return val
        #SEE OTHER !ADD-TYPE, may need to convert type to string for storage if cant use automatic json conversion

    def parms(self):
        # Build a dictionary from all the fields saved in the parms field
        return { k: self.forparms(k) for k in self._parmfields}

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
    _parentclass = Model    # Subclass this to be the singular class
    _selectallsql = "SELECT * FROM %s"
    _parmfields = []


    def __init__(self, ll):
        """
        Initialize an array of Models
        :param ll: iterator that returns a valid arg to the ModelXyz() esp int or sqlite3.Row
        """
        super(Models, self).__init__([(l if isinstance(l, Model) else self._parentclass(l)) for l in ll ])

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
        return db.sqlfetch(cls._selectallsql % cls._parentclass._tablename)

    @classmethod
    def find(cls, _skipNone=False, _verbose=False, **kwargs):
        """
        Do a SQL SELECT and return all results, see sqlpair for documentation of special arguments
        _skipnone   True if should ignore arguments that are None
        Returns a list which may be empty
        See Model.find if want a single item returned
        """
        keys, val1 = zip(
            *[SqliteWrap.sqlpair(key, val, parmfields=cls._parmfields) for key, val in kwargs.iteritems() if not (_skipNone and val is None)])
        vals = flatten2d(val1)
        sql = "SELECT * FROM %s WHERE %s" % (cls._parentclass._tablename, " AND ".join(keys))
        return cls(db.sqlfetch(sql, vals, verbose=_verbose))


class ModelExample(Model):
    _tablename = "modelexample"
    _createsql = "CREATE TABLE %s (id integer primary key, name text, father modelexample, siblings modelexamples, parms json, lastmod timestamp, tags tags)" % _tablename
    _insertsql = "INSERT INTO %s VALUES (NULL, NULL, NULL, NULL, NULL, NULL, NULL)" % _tablename
    _validtags = {"FOO"}
    _parmfields = {"pfield1": unicode, "pfield2": int, "mother": None, "parmstime": datetime, "parmsmodels": None}

ModelExample._parmfields["mother"]=ModelExample # Because undefined when defining _parmfields above

def convert_modelexample(s):
    # Note s is never None or Null etc, that skips the conversion and returns None
    return ModelExample(s)

sqlite3.register_converter("modelexample", convert_modelexample)  # Return JSON, could be dict or list


class ModelExamples(Models):
    _parentclass = ModelExample

ModelExample._parmfields["parmsmodels"]=ModelExamples   # Done here as undefined during definition of ModelExample

def convert_modelexamples(s):
    # s is a list of id's
    return ModelExamples(loads(s))

sqlite3.register_converter("modelexamples", convert_modelexamples)  # Return JSON, could be dict or list
#sqlite3.register_adapter(ModelExamples, dumps)   # Note this also covers Models which is a list

db = SqliteWrap("test.db")

def test():
    # Create table
    db.connect()
    try:
        ModelExample.createtable(dropfirst=True)    # ONLY WORKS ONCE
    except sqlite3.OperationalError as e:
        print e
    # Create object in table
    foo = ModelExample.insert(name="Foo")
    assert foo.name == "Foo", "name should be Foo as loads its "+(foo.name or "None")
    # Store something in it
    foo.update(name="Bar")
    # Retrieve it by id
    try:
        bar = ModelExample(111).load()
    except Exception as e:
        assert e.__class__ == ModelExceptionRecordNotFound
    else:
        assert False, "Should fail"
    bar = ModelExample(1)   # Retrieve it
    assert bar.name == "Bar", "Name should ahve been changed to Bar"  # Check its fields
    foo.update(tags=None) # Update and check
    assert not bar.tags, "Should be set to empty set by above"
    assert not bar.hastag("FOO"),"Should not have tag foo now"
    try:    # Check can't set invalid tag
        bar.settags("BAZ")
    except Exception as e:
        assert e.__class__ == ModelExceptionInvalidTag
    else:
        assert False, "Should fail to set invalid tag"
    assert not bar.hastag("BAZ"),"Should have tag foo now"
    bar.settags("FOO")
    assert bar.hastag("FOO"),"Should have tag foo now"
    assert bar.hastag("FOO"),"Saved version have tag foo now"
    assert bar.hasanytags(u"FOO"), "Should have any of FOO"
    assert bar.hasanytags(["FOO","XYZ"]), "Should have FOO"
    # Find it
    bar.cleartags("FOO")
    assert not bar.hastag("FOO"),"Should not have tag foo after clearing"
    assert not bar.hastag("FOO"), "Should not have tag foo now"
    bar.update(pfield1="Foo", pfield2=123)
    assert ModelExample(1).load().pfield2 == 123, "Should have set and retrieved it"
    baz = ModelExample.insert(name="Baz")
    bar.update(father=baz)
    assert ModelExample(1).load().father == baz, "Should have set father, uses __eq__ for comparisom"
    bar.update(mother=baz)
    assert ModelExample(1).load().mother == baz, "Should have set mother in parms field, uses __eq__ for comparisom"
    now = timestamp()
    bar.update(parmstime=now)
    assert ModelExample(1).load().parmstime == now, "Should round trip datetime"
    brother = ModelExample.insert(name="Brian")
    sister = ModelExample.insert(name="Jane")
    sibs = ModelExamples([brother, sister])
    bar.update(siblings = sibs)
    assert ModelExample(1).load().siblings.contains(brother)
    assert not ModelExample(1).load().siblings.contains(bar), "Shouldnt contain bar"
    bar.update(parmsmodels = sibs)
    assert ModelExample(1).load().parmsmodels.contains(brother), "Should find brother in the parmsmodels after roundtrip"
    brocopy = ModelExample(3)
    sibs.append(brocopy)    # Now got a duplicate
    assert len(sibs.set()) == 2 # set should delete duplicate
    assert len(ModelExamples.all()) == 4
    bar.delete()
    assert len(ModelExamples.all()) == 3
    assert len(ModelExamples.find(name="Brian")) == 1, "Should find one record"
    assert ModelExample.find(name="Brian") == brother, "Should find the brother record"
    db.disconnect()

def timestamp():
    return datetime.now()

def flatten2d(rr):
    return [ leaf for tree in rr for leaf in tree ]  # Super obscure but works and fast
    # See  http://stackoverflow.com/questions/952914/making-a-flat-list-out-of-list-of-lists-in-python/952952#952952