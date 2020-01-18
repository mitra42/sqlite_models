# encoding: utf-8

import sqlite3
from model import Model, Models, timestamp
from aenum import Enum # From aenum
from json import loads, dumps
import re                           # Regex
from sqlitewrap import SqliteWrap
import BaseHTTPServer       # See https://docs.python.org/2/library/basehttpserver.html for docs on how servers work
import urlparse             # See https://docs.python.org/2/library/urlparse.html

#from enum import Enum # From flufl.enum

"""
GOALS
- lightweight SMS server that can work with SMSRelay application
- build upon "Models" as an example

TODO
- add phonenumber as a type in SMSmessage and SMSgateway, and maybe use google phonenumbers library store in intl
- ignore spam numbers and short codes (maybe after get google phonenumbers working)
- handle expired
- Add priorities to dispatch patterns
- Match final version of SMSrelay android app
- http return errors using send_error

"""
class SMSstatus(Enum):
    QUEUED=1
    GATEWAY=2
    SENT=3
    DELIVERED=4
    FAILED=5
    INCOMING=10
    LOOP=11
    SPAM=12

    def __conform__(self, protocol):
        if protocol is sqlite3.PrepareProtocol:
            return self.value

    def adapt_smsmessagestatus(self):
        return self.value


def convert_smsmessagestatus(s): return SMSstatus(int(s))
#sqlite3.enable_callback_tracebacks(True)
sqlite3.register_converter("smsmessagestatus", convert_smsmessagestatus)
sqlite3.register_adapter(SMSstatus, SMSstatus.adapt_smsmessagestatus)

class SMSdispatchtype(Enum):
    STRINGIN=1
    REGEX=2


class SMSmessage(Model):
    _tablename = "smsqueue"
    _createsql = "CREATE TABLE %s (id integer primary key, status smsmessagestatus, gateway smsgateway, " \
                 "phonenumber text, message text, message_id text, timestamp datetime, tags tags )"
    _insertsql = "INSERT INTO %s VALUES (NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL)"
    _validtags = {}
    _parmfields = {}

    @property
    def _isloop(self):  # Check if its a loop, defined as message_id already seen
        return len(self._plural.find(message_id=self.message_id)) > 1

def convert_smsmessage(s):  return SMSmessage(s)
sqlite3.register_converter("smsmessage", convert_smsmessage)


class SMSmessages(Models):
    _singular = SMSmessage

    @classmethod
    def nextmessage(self,  gws, _verbose=False):
        mm = self.find(gateway=gws, status=SMSstatus.QUEUED, _verbose=_verbose)  # Look for queued on any of gateways
        if mm:
            return mm[0] if mm else None
        mm = self.find(gateway=gws, status=SMSstatus.FAILED, _verbose=_verbose)  # Look for failed and retry
        if mm:
            return random.choice(mm) if mm else None   #Fairly dumb way to do retries, from random FAILED

def convert_smsmessages(s): return SMSmessages(loads(s))
sqlite3.register_converter("smsmessages", convert_smsmessages)
SMSmessage._plural = SMSmessages

class SMSgateway(Model):
    _tablename = "gateway"
    _createsql = "CREATE TABLE %s (id integer primary key, name text, phonenumber text, battery_strength int, timestamp datetime, " \
                 "wifi_strength int, gsm_strength int, charging boolean, device_id int, ipaddr text, parms json, lastpolled datetime, lastincoming datetime, tags tags)"
    _insertsql = "INSERT INTO %s VALUES (NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL)"
    _validtags = {}
    _parmfields = {}
    _plural = None  # Set to SMSgateways after its definition

def convert_smsgateway(s):  return SMSgateway(s)
sqlite3.register_converter("smsgateway", convert_smsgateway)

class SMSgateways(Models):
    _singular = SMSgateway

    @classmethod
    def nextid(cls):
        return max([gw.device_id for gw in cls.all() if gw.device_id] or [1000]) + 1

    @classmethod
    def findOrCreateAndUpdate(cls, _verbose=False, device_id=None, phonenumber=None, ipaddr=None, **kwargs):
        """
        :param device_id:   Aribtrary string for hte device
        :param phonenumber: In international format +12345678901
        :param kwargs:      Any other args will be used to update the record
        :return: SMSGateways    List of matching gateways, creating one if non exist
        """
        gws = (phonenumber and cls.find(phonenumber=phonenumber, _verbose=_verbose)
               or (device_id and cls.find(device_id=device_id))
               or (ipaddr and cls.find(ipaddr=ipaddr))
               )
        if gws:
            for g in gws:
                g.update(_verbose=_verbose, device_id=device_id or g.device_id, phonenumber=phonenumber or g.phonenumber, ipaddr=ipaddr or g.ipaddr, **kwargs)
            return gws
        else:
            return cls(cls._singular.insert(_verbose=_verbose, device_id=device_id or SMSgateways.nextid(), phonenumber=phonenumber, **kwargs))

SMSgateway._plural = SMSgateways    # Set plural, can't do this before SMSgateways is defined.
def convert_smsgateways(s): return SMSgateways(loads(s))
sqlite3.register_converter("smsgateways", convert_smsgateways)


class SMSdispatcher(object):
    spam = [ "BUY ONE",]
    patterns = []

    @classmethod
    def isspam(cls, message):   # Checking spam is a method of the dispatcher as may be language or context dependent
        return any([sp in message.message for sp in cls.spam])

    @classmethod
    def update(self, **kwargs):
        if kwargs["type"] == SMSdispatchtype.REGEX:
            # Regex are compiled once to make them more efficient
            kwargs["regex"]=[re.compile(r) for r in kwargs["regex"]]    # Array of compiled regex
        self.patterns.append(kwargs)    # Append kwargs as a dict

    @classmethod
    def dispatch(cls, msg, gateway, **kwargs ):
        """
        A basic dispatcher, can be replaced in subclasses,
        returns array of dicts with response to queue
        See https://docs.python.org/3/howto/regex.html for syntax of regex
        """
        verbose = True
        if verbose: print "SMSdispatcher.dispatch",msg,kwargs
        if cls.isspam(msg):
            msg.update(status=SMSstatus.SPAM)
            return None
        for p in cls.patterns:
            if p["type"]==SMSdispatchtype.STRINGIN:
                for s in p["strings"]:
                    if s in msg.message:
                        if verbose: print "SMSdispatcher matched",s
                        return p["f"](msg)
            if p["type"]==SMSdispatchtype.REGEX:
                for s in p["regex"]:
                    m = s.search(msg.message)
                    if m:
                        if verbose: print "SMSdispatcher matched",m.group()
                        return p["f"](msg, m)

class SMSHTTPRequestHandler(BaseHTTPServer.BaseHTTPRequestHandler):
    # NOTE this is a code also in dweb (and more developed there) may want to pull changes from there if working on this
    dispatchclass = None

    def do_GET(self):
        verbose=True
        try:
            o = urlparse.urlparse(self.path)
            res = self.dispatchclass.dispatch(o.path[1:],
                                    **dict(urlparse.parse_qsl(o.query)))
            if verbose: print "do_GET",res
            if isinstance(res, dict):   # It should be, for returning via JSON
                res = dumps(res)
            self.send_response(200)
            self.send_header('Content-type', 'text/json')
            self.send_header('Content-Length', str(len(res)) if res else 0)
            self.end_headers()
            self.wfile.write(res)
        except Exception as e:
            #TODO - return error as 500
            raise e

    @classmethod
    def httpserver(cls, ipandport, dispatchclass):
        """
        Run a server that uses this class as its handler.
        """
        cls.dispatchclass = dispatchclass       # Stops circular reference
        BaseHTTPServer.HTTPServer( ipandport, cls).serve_forever()

class HTTPdispatcher():
    """
    Simple HTTPdispatcher,
    Subclasses should define "exposed" as a list of exposed methods
    """
    exposed = []

    @classmethod
    def dispatch(cls, req, **kwargs):
        verbose=True
        #"sms_poll": sms_poll,
        #"sms_incoming": sms_incoming
        if verbose: print "HTTPdispatcher.dispatch",req,kwargs
        if req in cls.exposed:
            return getattr(cls, req)(**kwargs)
        else:
            if verbose: print "HTTPdispatcher.dispatch unimplemented:"+req
            raise SMSRelayExceptionInvalidRequest(req=req)



class SMSrelay(HTTPdispatcher):   # Encapsulation of class methods that define this
    dispatcher = None       # Set to class to dispatch messages to
    exposed = ("sms_poll", "sms_incoming")

    @classmethod
    def sms_poll(cls, _verbose=False, sim_num=None, **kwargs):
        """
        sms_poll {'battery_strength': u'50', 'timestamp': u'2017-02-07T06:28Z', 'wifi_strength': u'0', 'gsm_strength': u'[38]',
         'charging': u'true', 'device_id': u'1007', 'sim_num': u'[14159969138]'}

        #TODO will need wrapping in simple HTTP server to generate json string and http headers, or calling from cherrypy
        # sim_num was sent as u'[1234,5678]', so not expanded properly, now not sent, was doing sim_num=loads(sim_num), before passing to findOrCreateAndUpdate
        """
        gws = SMSgateways.findOrCreateAndUpdate(_verbose=False, **kwargs)    # All matching gateways (multiple if multi-sim
        gws.update(lastpolled=timestamp())
        msg = SMSmessages.nextmessage(gws, _verbose=_verbose)
        if not msg:
            return {}
        else:
            msg.update(status=SMSstatus.GATEWAY)
            msg.update(status=SMSstatus.SENT)  # Simulate sent TODO replace with response from gateway when that function available in Android SMSRelay
            gw = msg.gateway
            return {
                'timestamp': timestamp().strftime('%Y-%m-%dT%H:%MZ'),  # Can change the format if the Relay needs a different type
                'message_id': msg.message_id,
                'message': msg.message,
                'to': msg.phonenumber,          # TODO field name might change
                'send_from': gw.phonenumber,
                'device_id': gw.device_id
            }

    @classmethod
    def sms_incoming(cls, **kwargs):
        # e.g. {'timestamp': u'2017-02-08T05:37:06Z', 'message': u'lala', 'from': u'+16177179014',
        # 'sent_to': u'14159969138', 'message_id': u'619472592'}
        verbose=True
        kwargs["phonenumber"] = kwargs["from"]    # SMSmessage uses phonenumber for both incoming and outgoing
        del(kwargs["from"])
        gws = SMSgateways.findOrCreateAndUpdate(device_id=kwargs.get("device_id"), phonenumber=kwargs.get("sent_to"))
        gw = gws[0] # Should always be just 1
        gw.update(lastincoming=timestamp())
        del(kwargs["sent_to"])  # Dont store on message, use gw
        del(kwargs["device_id"])  # Dont store on message, use gw
        msg = SMSmessage.insert(gateway=gw, status=SMSstatus.INCOMING, **kwargs)
        if msg._isloop:
            msg.update(status=SMSstatus.LOOP)
        else:
            # Send it the app
            response = cls.dispatcher.dispatch(msg=msg, gateway=gws)
            if verbose: print "sms_incoming resp=",response
            # The dispatcher can send messages directly through sms_queue OR return one or more dicts { phonenumber="+1234", message="Hello"}
            if isinstance(response, (list, tuple)):
                for r in response:
                    cls.sms_queue(gateway=gw, **response)
            elif isinstance(response,(dict)):
                cls.sms_queue(gateway=gws[0], **response)   # Always queue on first gateway if multiple (shouldnt be multiple since sms_incoming specifies phone number
            else:
                pass    # Nothing to send out

    @classmethod
    def sms_queue(self, **kwargs):
        kwargs["status"] = SMSstatus.QUEUED
        return SMSmessage.insert(**kwargs)

    @classmethod
    def setup(cls, databasefile=None, createTables=False, dropTablesFirst=False, dispatcher=None, httpserver=None):
        """
        :param databasefile:        Database file to connect to
        :param createTables:        True if should create tables in file
        :param dropTablesFirst:     True to clear tables first
        :param dispatcher:          Class to handle incoming SMS
        :return:
        :exception:                 sqlite3.OperationalError if SQL fails e.g. if don't drop tables but they exist already
        """
        if databasefile:
            SqliteWrap.setdb(databasefile)
            SqliteWrap.db.connect()
        if createTables:
            try:
                SMSmessage.createtable(dropfirst=dropTablesFirst)
                SMSgateway.createtable(dropfirst=dropTablesFirst)
            except sqlite3.OperationalError as e:
                print e
        if dispatcher:
            SMSrelay.dispatcher=dispatcher  # Setup for testing
        if httpserver:
            SMSHTTPRequestHandler.httpserver(httpserver, cls)



    @classmethod
    def done(cls):
        SqliteWrap.db.disconnect()



def test():
    print "Testing SMS Relay"
    SMSrelay.setup(
        databasefile="smsmessagetest.db",           # Connect to the database in this test file
        createTables=True, dropTablesFirst=True,    # Create tables, removing whatever was there first
        dispatcher = SMSdispatcher,                 # Class to handle incoming
    )
    assert SMSstatus.QUEUED.name == "QUEUED", "Check enumerations loading correctly"
    assert isinstance(SMSstatus.QUEUED, SMSstatus), "Should be an instance if want conform to work"
    resp = SMSrelay.sms_poll(**{'battery_strength': u'50', 'timestamp': u'2017-02-07T06:28Z', 'wifi_strength': u'0', 'gsm_strength': u'[38]',
     'charging': u'true', 'device_id': u'1007'})
    # Side effect of creating Gateway(1)
    assert resp == {}, "Expect empty response as nothing queued"
    gw1 = SMSgateway(1)
    msg_helloworld = SMSrelay.sms_queue(gateway=gw1, phonenumber="+12345678901", message="Hello world")
    resp = SMSrelay.sms_poll(**{'battery_strength': u'50', 'timestamp': u'2017-02-07T06:28Z', 'wifi_strength': u'0', 'gsm_strength': u'[38]',
     'charging': u'true', 'device_id': u'1007'})
    assert resp["message"] == "Hello world", "Expect to find the message queued above"
    assert len(SMSgateways.all()) == 1
    # Set up dispatcher for a trivial response
    SMSdispatcher.update(strings = ["hello","bonjour"], type=SMSdispatchtype.STRINGIN,
                         f=lambda msg: { "phonenumber": msg.phonenumber, "message": "Thanks a bunch" } )
    SMSdispatcher.update(regex = [r"name is (?P<name>[A-Za-z ]+?) from (?P<from>[A-Z][a-zA-Z]+)"], type=SMSdispatchtype.REGEX,
                         f=lambda msg, r: { "phonenumber": msg.phonenumber, "message": "Hi %s how is the weather in %s" % (r.group("name"),r.group("from")) } )

    resp = SMSrelay.sms_incoming(**{'timestamp': u'2017-02-08T05:37:06Z', 'message': u'hello', 'from': u'+16177179014',
                                    'sent_to': u'+14159969138', 'device_id': u'1007', 'message_id': u'100001'})
    assert len(SMSgateways.all()) == 1
    # Should queue a message "Thanks a bunch"
    resp = SMSrelay.sms_poll(_verbose=False, **{'battery_strength': u'50', 'timestamp': u'2017-02-07T06:28Z', 'wifi_strength': u'0', 'gsm_strength': u'[38]',
           'charging': u'true', 'device_id': u'1007', 'sim_num': u'[14159969138]'})
    assert len(SMSgateways.all()) == 1
    assert resp["message"] == "Thanks a bunch", "Should be response from TestDispatcher"

    # Test regex
    resp = SMSrelay.sms_incoming(**{'timestamp': u'2017-02-08T05:37:06Z', 'message': u'My name is Fred from London', 'from': u'+16177179014',
                                    'sent_to': u'+14159969138', 'device_id': u'1007', 'message_id': u'100004'})
    resp = SMSrelay.sms_poll(_verbose=False, **{'battery_strength': u'50', 'timestamp': u'2017-02-07T06:28Z', 'wifi_strength': u'0', 'gsm_strength': u'[38]',
           'charging': u'true', 'device_id': u'1007', 'sim_num': u'[14159969138]'})
    assert resp["message"] == "Hi Fred how is the weather in London", "Should handle regex"

    # Test loops
    resp = SMSrelay.sms_incoming(**{'timestamp': u'2017-02-08T05:37:06Z', 'message': u'hello', 'from': u'+16177179014',
                                    'sent_to': u'+14159969138', 'device_id': u'1007', 'message_id': u'100001'})
    resp = SMSrelay.sms_poll(_verbose=False, **{'battery_strength': u'50', 'timestamp': u'2017-02-07T06:28Z', 'wifi_strength': u'0', 'gsm_strength': u'[38]',
           'charging': u'true', 'device_id': u'1007', 'sim_num': u'[14159969138]'})
    assert len(resp) == 0, "Should ignore loops"

    # Test spam
    resp = SMSrelay.sms_incoming(**{'timestamp': u'2017-02-08T05:37:06Z', 'message': u'BUY ONE', 'from': u'+16177179014',
                                    'sent_to': u'+14159969138', 'device_id': u'1007', 'message_id': u'100003'})
    resp = SMSrelay.sms_poll(_verbose=False, **{'battery_strength': u'50', 'timestamp': u'2017-02-07T06:28Z', 'wifi_strength': u'0', 'gsm_strength': u'[38]',
           'charging': u'true', 'device_id': u'1007', 'sim_num': u'[14159969138]'})
    assert len(resp) == 0, "Should ignore spam"


    SqliteWrap.db.disconnect()