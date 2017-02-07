
from .model import Model

import cherrypy
from decimal import Decimal
from datetime import datetime

from constants import LOGCREATED, LOGSET, FINDERR, LANG_DEFAULT, \
    NULLNONE, ONLYONE, ONEORNONE, NULLERR
from utils import rows2unicode, trace, lprint, sqlSend, sqlFetch, sqlFetch1, debug, flatten2d, sqlpair, dictdiff, \
    timestamp
from errors import FindError, SMSErrorP, Error, SMSError
from xmlHelper import XMLHelper


# TODO - below here is old Record class

class Record(Model):
    """
    It has key attributes
    _r  which containst the fields of the SQL record once _loaded - access through self.r(name)
    _tags which expands _r["tags"] into a list   - access via self.hastag(tag)
    _id which is the id and should match _r["id"] if loaded - access through self.id

    Each subclass should provide createstr and insertstr
    """

    # Can be overridden in class
    _lastmodfield = False  # overridden to True if should save modification, e.g. Contact, Meter
    recopystr = "INSERT INTO %s SELECT * FROM %s"  # Default recopy string, subclassed in any class where structure changes
    postcreate = None
    debug = False  # Can be overwritten in individual classes
    parmfields = []  # List of fields held in "parms", typically subclassed
    parmfieldsvalue = []  # Subset of fields that should be converted to/from Value
    fieldrangefields = []  # ["maxcontinuous","recoverytime","maxpeak","peaktime", "groupid", "credittype"]
    devicesettingfields = []  # ["maxcontinuous","recoverytime","maxpeak","peaktime", "groupid", "credittype"]
    strfields = []  # Fields that must be strings
    intfields = []  # Fields that must be ints
    floatfields = []  # Fields that must be floats
    timefields = []  # Fields that must be datetime


    @classmethod
    def parms2sql(cls, parms):
        """
        Convert Value fields to sql as a tuple (amount, unit-id)
        Convert Datetime fields to secs ?
        """
        from models.unit import Value
        pp = parms  # Have to copy it because otherwise will edit dic in place (on the object)
        for k in cls.parmfieldsvalue:
            val = pp.get(k, None)
            if val is not None and isinstance(val, Value):
                unitid = None if val.unit(ONEORNONE) is None else val.unit(ONLYONE).id
                pp[k] = (val.dd(), unitid)  # storing ( float, unitid)  # See matching code in utils.py:sqlpair
        #timefields handled in parms()
        return pp

    def sql2parms(self, parms):
        """
        Convert Value fields from sql as a tuple (amount, unit-id)
        """
        for k in self.parmfieldsvalue:
            v = parms.get(k, None)
            if isinstance(v, (list, tuple)):
                from models.unit import Unit, Value
                if v: parms[k] = Value(Decimal(v[0]), Unit(v[1]))  # storing floats
        #XXX Note was code here to handle time, but handled in load now
        return parms

    # ====== Accessing fields through cached _r ===========

    def logs(self, nullbehavior, desc=True, limit=0):
        """
        Get all the log records of an object
        """
        from models.log import Log
        return Log.byRecord(self, nullbehavior, desc, limit)

    @classmethod
    def shouldbe(cls, obj, nullbehavior, errno):
        """
        Create a obj from an id,
        Note this doesn't create it in the database, or check for its existence (use .mustexist() to check and populate).
        This is used for Contact and Unit, and might be for others
        It is subclassed by Meter (which assumes labels); and similar version in PhoneNumber and Deal which knows about subtypes
        ERR 59 - blank, 25 numbers only
        """
        if isinstance(obj, cls):
            return obj
        elif obj is None or (len(unicode(obj)) == 0):
            if nullbehavior in (NULLERR, ONLYONE):
                if errno is not None:
                    raise SMSErrorP(errno, {})  # Errno generate a specific error to the number
                else:
                    raise SMSErrorP(59, {"field": cls.__name__})  # 'Please do not leave the {field} field blank
            else:  # nullbehavior == NULLNONE
                return None
        else:
            try:
                id = int(obj)
            except:
                if errno is not None:
                    raise SMSErrorP(errno, {})  # Errno generate a specific error to the number
                else:
                    raise SMSErrorP(25, {})  # Numbers only
            return cls(id)


            # ===== TAGS handling - a list stored in repr form in one column of sql

    ####### Methods for altering things #######

    @classmethod
    def logIdUpdatedField(cls, id, field, newvalue, cls2,
                          login):  # XXXLOGCONTACT - change parameters then use Log.iinsertNew
        """
        Log a change to a field, note in some cases e.g. setCmd it will be a pseudofield not in database
        """
        from .log import Log  ## Avoid cyclic dependencies
        if not type(newvalue) == int:
            logstr = "updated field: " + field + " to '" + unicode(newvalue) + "'"
            newvalue = None
            Log.iinsert(cls, id, cls2, newvalue, LOGSET, logstr, None, login)
        else:
            Log.iinsert(cls, id, cls2, newvalue, LOGSET, "updated field: " + field, None, login)

    def logUpdatedField(self, field, newvalue, cls2, login):
        self.logIdUpdatedField(self.id, field, newvalue, cls2, login)

    # ===== NULLBEHAVIOR === DEALING WITH PRESENCE OR ABSENCE OF RESULTS =====

    @classmethod
    def NullBehavior(cls, where, nullbehavior):
        """
        Perform null behavior when know its None
        ERR 52 if neither NULLNONE or ONEORNONE
        """
        assert nullbehavior != FINDERR, "NullBehavior doesnt support FINDERR"
        if nullbehavior == NULLNONE:
            return []
        if nullbehavior == ONEORNONE:
            return None
        raise SMSErrorP(52, {"cls": cls.typetable, "where": where})  # XXX err 52 doesn't use "where" yet

    @classmethod
    def checkNone(cls, r, where, nullbehavior, lamb):
        """
        Analog of checkNull where starting with a single object
        This doesn't quite work yet, cherryRun.accounts would like to use it, but this returns [ [ accounts ] ]
        """
        assert nullbehavior != FINDERR, "checkNone doest support FINDERROR"
        if r is None:
            return cls.NullBehavior(where, nullbehavior)
        # Cases where return an object
        if nullbehavior == ONLYONE or nullbehavior == ONEORNONE:
            if lamb is None:
                return r
            else:
                return lamb(r)
        # Cases where return an array
        if lamb is None:
            return [r]
        else:
            return [lamb(r)]

    @classmethod
    def checkNull(cls, rr, where, nullbehavior, lamb):
        """
        Return appropriately based on nullbehavior and size of rr
        where is the inner part of an error message
        lamb is a function that can be applied to anything returned
        nullbehavior controls behavior if field doesn't point to anything
        NULLERR Err 52; NULLNONE - return [ ]  -
        ONLYONE says only ok if exactly one found, and return err 63 if >1 or 52 if none
        ONEORNONE says return obj if found, or None if not, err 63 if >1
        FINDERR - Err 51 if found
        All of these errors should be caught before the user sees them - 51 is (except in createNewAgent),
        52 and 63 still need tracing
        ERR 51,52,63
        """
        if nullbehavior == FINDERR:
            if len(rr) > 0:
                raise SMSErrorP(51, {"where": where})
            else:
                return None
        if (len(rr) == 0) and (nullbehavior != NULLNONE):
            if nullbehavior == ONEORNONE:
                return None
            else:
                # i.e.. nullbehavior == NULLERR|ONLYONE)
                raise SMSErrorP(52, {"cls": cls.typetable, "where": where})  # XXX err 52 doesn't use "where" yet
        # Either have >0 objects or 0 objects and NULLNONE
        # Cases where return an object,
        if nullbehavior == ONLYONE or nullbehavior == ONEORNONE:
            if len(rr) == 1:
                if lamb is None:
                    return rr[0]
                else:
                    return lamb(rr[0])
            else:
                raise SMSErrorP(63, {"where": where})  # XXX note err 63 doesn't use "where" yet
        # Cases where return an array
        if lamb is None:
            return rr
        else:
            return [lamb(r) for r in rr]

            # ===== FINDING  ===================

    # ======= Integrity checking methods - not used in operations, just for debugging #######

    @classmethod
    def integrityCheckClass(cls):
        """
        Check the integrity of database for a specific class,
        Empty method for classes where not needed
        """
        cls.integrityCheckTableRow()

    @classmethod
    def integrityCheckField(cls, field, min, max):
        """
        Check all occurances of <field> are between min and max inclusive
        """
        rr = sqlFetch("SELECT id, " + field + " FROM " + cls.typetable + " WHERE " + field + " < " + str(
            min) + " OR " + field + " > " + str(max))
        for i in rr:
            trace("E", "INTEGRITY:", "In: %s id=%d %s is %d but supposed to be %d to %d"
                  % (cls.typetable, i[0], field, i[1], min, max))

    @classmethod
    def integrityTypedPointer(cls, typefield, typedidfield):
        """
        Check that all occurences in <typefield,typedidfield> correspond
        to a record in appropriate table or are None
        """
        # print "Checking typed pointers in ",cls.typetable
        # Could check like following BUT log contains pointers to deleted records so no point
        # rr = sqlFetch("SELECT id,typedid FROM log WHERE type = 7 AND typedid NOT IN (SELECT id FROM meter)",verbose=True)
        pass

    @classmethod
    def integrityCheckPointer(cls, field, destcls, nullok):
        """
        Check that all occurences in <field> correspond to a record of appropriate class
        This is redundant if using a database that enforces constraints
        """
        # print "Checking non-zero pointers in ",table, ".", field, " point to ", desttable
        if nullok == NULLNONE:
            w = " WHERE " + field + " !=0"
        else:
            w = ""
        rr = sqlFetch("SELECT id, " + field + " FROM " + cls.typetable + w)
        for i in rr:
            target = (i[1],)
            if target != 0:  # Can only be Zero if NULLNONE so skip it
                cnt = sqlFetch1("SELECT COUNT(id) FROM " + destcls.typetable + " WHERE id=?", target)
                if cnt[0] != 1:
                    lprint("INTEGRITY: In:", cls.typetable, "id=", i[0], " ",
                           field, " ptr to", i[1], "which exists", cnt[0], "times in", destcls.typetable)

    @classmethod
    def integrityCheckMaxPointer(cls, field, desttable, destfield):
        # print "Checking pointers in ",table, ".", field, " point to maximum of", desttable, ".",destfield
        rr = sqlFetch("SELECT id, " + field + " FROM " + cls.typetable)
        for i in rr:
            target = (i[0],)
            maxed = i[1]
            cnt = sqlFetch1("SELECT MAX(id) FROM " + desttable + " WHERE " + destfield + "=?", target)
            if cnt[0] != maxed:
                lprint("INTEGRITY: In ", cls.typetable, "id=", i[0], field, "is",
                       i[1], "but max matching id in", desttable, "is", cnt[0])

    @classmethod
    def integrityCheckTableRow(cls):
        for r in cls.allobjs():
            # print r.id
            try:
                r.tablerow(LANG_DEFAULT)
            except SMSError as e:
                print "Tablerow Error on", r.typetable, r.id, e.message()

                # ========  Methods of Record used for the administrative and user interfaces via web ########

    @classmethod
    def XMLdump(cls, field, val, numlines):
        """
        Return a data structure suitable for sending to XML (could split into a JSON version)
        Note also appears to be used by GetHTML2 , used by transactions list
        field can be comma separated in which case val should be just 1 and it looks for val in multiple fields
        """
        if field is not None:
            l = len(field.split(","))
            if l > 1:  # More than one field specified
                val = ",".join((val,) * l)  # Turn "VAL" into e.g. "VAL,VAL" for allrecords
        rr = cls.allrecords(numlines, field, val)
        return (XMLHelper.w("table",
                            {'name': cls.typetable, 'field': field, 'val': val},
                            (XMLHelper.w("fields", None,
                                         (XMLHelper.w("field", {"name": "empty"})
                                          if (len(rr) == 0)
                                          else XMLHelper.ww("field", "name", rr[0].keys())
                                          )
                                         ),
                             XMLHelper.w("rows", None, XMLHelper.wrr("row", rr))
                             )
                            ))

    # ========= OTHER METHODS ============

    def idAndName(self):
        """
        Get the tuple of id and name, only used in debug
        Note that name() may be subclassed to be something other than the name field
        and idAndName itself could be subclassed
        """
        return self.id, self.name()

    def errname(self):
        """
        Return a name suitable for including in errors.
        """
        return "%s %d" % (self.typetable, self.id)

    @classmethod
    def idsAndNames(cls, rr):
        """
        Get the id, name tuple for each of rr
        """
        return [r.idAndName() for r in rr if r is not None]

    @classmethod
    def selectarray(cls, field=None, val=None, objs=None):
        """
        Get a dict of ids and names suitable for example for a HTML SELECT
        """
        if objs is None:
            rr = cls.allrecords(0, field, val, False)
            return {i["id"]: {"id": i["id"], "option": unicode(i["name"])} for i in rr}
        else:
            objs = cls.set(objs)
            return {o.id: {"id": o.id, "option": o.name()} for o in objs}

    @classmethod
    def _allrecords(cls, r):
        """
        Stub to be subclassed
        Deal does this
        """
        # Tried subclassing this, but it reordered the dictionary which was not what I wanted
        return r

    @classmethod
    def allrecords(cls, limit=0, field=None, val=None, desc=True):
        """
        Note this can be subclassed to decode a field, for example Deal *used to* pre 1sept2015 do this to unpickle kids
        field and cal can be comma separated strings with same number of parts
        """
        # print "allrecords",cls.typetable,limit,field,val,desc
        selectstr = "SELECT * FROM %s " % cls.typetable
        if field is not None:
            selectstr += "WHERE " + " OR ".join([(f + " = ?") for f in field.split(',')])
        if desc:
            selectstr += " ORDER BY id DESC"
        if limit > 0:
            selectstr += " LIMIT %s" % limit
        # print selectstr
        if val is None:
            rr = sqlFetch(selectstr)
        else:
            rr = sqlFetch(selectstr, val.split(','))
        return [cls._allrecords(r) for r in rr]

    @classmethod
    def allobjs(cls, field=None, val=None, desc=False, limit=0):
        return [cls(r) for r in cls.allrecords(field=field, val=val, desc=desc, limit=0)]

    def as_dict(self):
        """
        Return a dict representation
        """
        return dict((k, self.r(k)) for k in self.fields)

    def sameUnit(self, rec):
        """
        Check if rec has same units as self
        Works for Account, Agent, Deal, Meter, Payment, Transaction, Unit
        """
        return self.unit(ONLYONE).sameAs(rec.unit(ONLYONE))


    # ========== UI SUPPORT ==============
    def tablerowtags(self, strings):
        """
        Return a string for the tags, if tag is not in strings then not returned
        """
        return ", ".join([strings[k] for k in strings.keys() if self.hastag(k)])

    def diff(self, rec2):
        # Utility to compare two objects
        r1 = dict(self.load()._r)
        r2 = dict(rec2.load()._r)
        for k in ("parms",):  # May need other fields that are arrays
            if r1.get(k, None) and r2.get(k, None):
                r1[k] = self.sql2parms(loads(r1[k]))
                r2[k] = self.sql2parms(loads(r2[k]))
                dictdiff(r1[k], r2[k])
        dictdiff(r1, r2)
        print "<", r1
        print ">", r2


######### Now one class to bind them all ###############

class RecordClasses:
    typedclasses = [0]

    # ClassDropOrder and typedclasses are setup in setClassDropOrder

    def __init__(self):
        raise (Error("Should never be instantiating an instance of this"))

    @classmethod
    def createTables(cls):
        """
        Create the full set of tables for each subclass of Record
        """
        # loop through classes to do this
        trace("L", "", "Creating Tables")
        # Order of dropping tables is significant, because of Foreign Key Constraints
        for i in cls.ClassDropOrder:
            # print "Dropping:", i.typetable
            try:
                sqlSend("DROP TABLE IF EXISTS " + i.typetable)
            except sqlite3.IntegrityError as e:
                print e  # Note using print since running from quickupdate
                print "on table", i.typetable
            cherrypy.thread_data.conn.commit()
        for i in reversed(cls.ClassDropOrder):  # cls.typedclasses: # First class is empty
            # print "Creating:", i.typetable
            if i != 0:
                i.createtable()
        cherrypy.thread_data.conn.commit()

    @classmethod
    def XMLdumpTables(cls, table, field, val, numlines):
        """
        Return an XML dump for either one table, or if table="all" then all tables
        field can be comma separated in which case val should be just 1 and it looks for val in multiple fields
        """
        if table == "all":
            # loop through classes to do this
            o = XMLHelper.w("tables", None, (("" if (i == 0 or i is None) else i.XMLdump(field, val, numlines)) for i in
                                             cls.typedclasses))
        else:
            o = XMLHelper.w("tables", None, Record.tableToClass(table).XMLdump(field, val, numlines))
        return o

    @classmethod
    def integrityCheck(cls):
        # print "Checking Integrity"
        for i in reversed(cls.ClassDropOrder):  # cls.typedclasses: # First class is empty
            # print i.typetable
            if i != 0:
                i.integrityCheckClass()

    @classmethod
    def recopy_all(cls, verbose=True):
        """
        Copy all the database tables
        Note this would typically be used if a constraint has been removed and AFTER the "create" string was changed in the appropriate models/* file
        This should normally only be called from quickupdate.py when server is NOT running
        """
        # This list should match the list in cherryserver.py - if it doesnt then a constraint might fail
        # Before calling from quickupdate it will need to set ClassDropOrder

        from utils import sqlSend  # Avoid dependency of Record on test code
        for recordclass in reversed(cls.ClassDropOrder):
            print "Recopying", recordclass.typetable
            recordclass.recopy(False, verbose)

        for recordclass in cls.ClassDropOrder:
            # print "Dropping",recordclass.typetable
            sqlSend("DROP TABLE IF EXISTS %s" % recordclass.typetable + "_old", verbose=verbose)

    @classmethod
    def table2id(cls, tablename):
        """
        Turn a tablename into a typeno (for example to lookup in Log.typeid or Log.bytype
        """
        for subclass in cls.typedclasses:
            if subclass != 0 and subclass is not None and subclass._tablename == tablename:
                return subclass.typeno
        return 0  # Unknown table

    @classmethod
    def id2table(cls, id):
        if id is None or id == 0: return None
        cls2 = cls.typedclasses[id]
        if cls2 is None: return None
        return cls2.typetable

    @classmethod
    def integrityTags(cls, fix):
        for cls in RecordClasses.ClassDropOrder:
            cls.integrityTags(fix)  # Comment out except if (rarely) check tags

    @classmethod
    def setClassDropOrder(cls):
        # See other !ADDRECORDSUBCLASS if adding subclass of Record
        from models.account import Account
        from models.contact import Contact
        from models.device import Device
        from models.gateway import Gateway
        from models.kopokopoLog import KopoKopoLog
        from models.econetzimLog import EconetZimLog
        from models.meterQueryLog import MeterQueryLog
        from models.airtelZamLog import AirtelZamLog
        from models.pagaLog import PagaLog
        from models.flutterwaveLog import FlutterwaveLog
        from models.MTNZambiaLog import MTNZambiaLog
        from models.location import Location
        from models.log import Log
        from models.manufacturer import Manufacturer
        from models.meter import Meter
        from models.payment import Payment
        from models.phone import Phone
        from models.phoneSession import PhoneSession
        from models.relation import Relation
        from models.rep import Rep
        from models.scratch import Scratch, ScratchBatch
        from models.smsLog import SMSLog
        from models.transaction import Transaction
        from models.unit import Unit
        from models.xmlVendLog import XMLVendLog
        from deals.deal import Deal
        # This is the order in which classes are dropped, later classes should not have SQL constraints refering to earlier
        # See other !ADDRECORDSUBCLASS
        cls.ClassDropOrder = (
        MTNZambiaLog, FlutterwaveLog, PagaLog, AirtelZamLog, MeterQueryLog, EconetZimLog, KopoKopoLog, Scratch,
        ScratchBatch, SMSLog, Transaction, Meter, Device, Log,
        Manufacturer, Payment, Phone, Deal, Gateway, Relation,
        Account,  # After Deal, Transaction, Agent
        Location,  # After meter, before Rep
        Rep, Contact, Unit, PhoneSession, XMLVendLog,
        )
        # See other !ADDRECORDSUBCLASS  - the position here must match the typeno in the new class
        cls.typedclasses = [0, Account, None, Contact, Device, Log,
                            Manufacturer, Meter, Payment, Phone,
                            PhoneSession, SMSLog, Deal, Transaction,
                            Unit, XMLVendLog, Rep, Gateway, Relation, Scratch, ScratchBatch,
                            KopoKopoLog, EconetZimLog, MeterQueryLog, AirtelZamLog, Location, PagaLog, FlutterwaveLog,
                            MTNZambiaLog]  # Note can reuse 2 (was Agent)


class Records(object):
    """
    A class to deal with arrays of records
    """

    @classmethod
    def sameAs(cls, rr):
        """
        Check if rr are all the same thing
        This could be improved possibly to allow an array instead
        """
        if len(rr) <= 1:  # Item always sameAs itself, or empty list
            return True
        id = rr[0].id
        for r in rr[1:]:
            if r.id != id:
                return False
        return True

    @classmethod
    def toreps(cls, rr):
        """
        Get the list of reps that rr responds to as a set of non-empty reps
        """
        if not rr:
            return set([])
        if not isinstance(rr, (list, tuple, set)):
            return set([rr.rep(ONEORNONE)])
        return set([x for x in [r.rep(ONEORNONE) for r in rr if r] if x])


def shouldbe(obj, cls, nullbehavior, errno):
    """
    Check if obj is a valid cls
    cls can be a subclass of Record or it can be any of str, int, float, bool
    ERR 58 if it doesnt match
    ERR 59 if its empty and nullbehavior=NULLERR
    !?! The use of this code needs cleaning up - Jona used it widely, and it should only really be used when there
          is a place to check a system assumption, not a check of user entered data.
    """
    # The strings below as a result dont need to be translated since a user should never see them.
    # There are currently no tests in run_tests that generate these kinds of errors so this can be considered non-urgent until some
    # use cases are found that generate them
    objtype = [None, "text", "whole number", "decimal number", "boolean"]
    ## OBS: objtypeSP
    # objtypeSP = [None, "texto", "número entero", "número decimal", "booleano"]

    if obj is None or (len(unicode(obj)) == 0):

        if nullbehavior in (ONLYONE, NULLERR):
            if errno is not None:
                raise SMSErrorP(errno, {})  # Errno generate a specific error to the number
            else:
                raise SMSErrorP(59, {"field": cls.__name__})  # 'Please do not leave the {field} field blank
        elif nullbehavior == NULLNONE:
            return []
        else:  # nullbehavior == NULLNONE   XXX This is actually wrong, if NULLNONE should return [ ] but will most likely break lots of things

            return None

    if isinstance(obj, cls):
        return obj
    elif cls == int:
        try:
            return int(obj)
        except:
            if errno is not None:
                raise SMSErrorP(errno, {})  # Errno generate a specific error to the number
            else:
                raise SMSErrorP(25, {})  # Numbers only
    elif cls == float:
        try:
            return float(obj)
        except:
            if errno is not None:
                raise SMSErrorP(errno, {})  # Errno generate a specific error to the number
            else:
                raise SMSErrorP(25, {})
    elif cls == Decimal:
        try:
            # WE are trying to catch cases where floats are turned into Decimals.
            # its safe to comment this line out if there are problems BUT please file a bug and let Mitra know
            assert not isinstance(obj, float), "really shouldnt be a float, one way to catch it ..."
            return Decimal(obj)
        except Exception as e:
            # raise e  # can temporarily Uncomment to look at the actual error
            if errno is not None:
                raise SMSErrorP(errno, {})  # Errno generate a specific error to the number
            else:
                raise SMSErrorP(25, {})  # Integers only
    elif cls == datetime:
        try:
            return datetime.strptime(obj, "%Y-%m-%d %H:%M:%S.%f")
        except:
            try:
                return datetime.strptime(obj, "%Y-%m-%d %H:%M:%S")
            except:
                try:
                    return datetime.strptime(obj, "%Y-%m-%d %H:%M")
                except:
                    try:
                        return datetime.strptime(obj,
                                                 "%Y-%m-%d")  # Raise exception if fails - shouldnt as should always come from UI
                    except:
                        try:
                            return parser.parse(obj)  # Has a good guess at user generated ones
                        except:
                            # raise e  # can temporarily Uncomment to look at the actual error
                            if errno is not None:
                                raise SMSErrorP(errno, {})  # Errno generate a specific error to the number
                            else:
                                raise SMSErrorP(169, {})  # Invalid date format
    else:
        try:
            if cls in (str, unicode):
                item = objtype[1]
                return unicode(obj)  # XXXUNICODE - should probably return unicode, as str value might be non-ascii
            elif cls == bool:
                item = objtype[4]
                if obj in [None, False, 0, '0', 'False', 'false',
                           '']:  # Note Javascript will send lower case false or true
                    return False
                elif obj in [True, 1, '1', 'True', 'true']:
                    return True
                else:
                    if errno is not None:
                        raise SMSErrorP(errno, {})  # Errno generate a specific error to the number
                    else:
                        return SMSErrorP(104, {"field": unicode(obj)})  # input not recognized as boolean
            elif issubclass(cls,
                            Record):  # Note we know its not an instance or would have been returned above so return an error
                raise SMSErrorP(58, {"obj": unicode(obj),
                                     "cls": cls.typetable})  # Note typetables aren't translated because this error should never be seen by a user
            else:  # We aren't checking
                lprint("INTERNAL ERROR isinstance obj:", unicode(obj), "cls:", cls.__name__)
        except SMSError as e:
            raise e
        except:
            raise SMSErrorP(58, {"obj": unicode(obj), "cls": item})


def hint2lang(langhint):
    """
    Guess what language to use for output, based on a hint provided
    If langhint is an int (LANG_EN or LANG_SP) then just return it as we already know the language.
    If its a string, presume its a phone number, turn it into a PhoneNumber and ask that.
    Anything else passed should have a language() method
    """
    from models.phone import PhoneNumber
    if langhint is None:
        return LANG_DEFAULT
    if isinstance(langhint, int):
        return langhint
    if isinstance(langhint, basestring):  # Try a string (ascii or unicode) and try as a phone number
        try:
            langhint = PhoneNumber.fromString(langhint)  # ERR (14,25,31, 32 all bad phone number)
        except SMSError as unused:
            # Typically this will happen when number entered by a user, e.g. at login
            return LANG_DEFAULT  # Bad number, can't guess
    # Commented out because if pass any class it should have a language() method
    # if isinstance(langhint, (PhoneNumber, Phone, Entity, SM)): # All these have a language method (PhoneNumber is simplest)
    l = langhint.language()
    return LANG_DEFAULT if l is None else l
