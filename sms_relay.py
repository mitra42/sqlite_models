# encoding: utf-8

import sqlite3
from model import Model, Models, timestamp
from aenum import Enum # From aenum
from json import loads, dumps
#from enum import Enum # From flufl.enum

"""
Example application using Models, stand alone support for SMS-Relay

GOALS
- lightweight framework for writing SMS applications

TODO
- add phonenumber as a type in SMSmessage and SMSgateway, and maybe use google phonenumbers library store in intl
- ignore spam numbers and short codes (maybe after get google phonenumbers working)
- clever dispatcher that can see message patterns or simple strings
- handle expired

EXAMPLES OF CALLS


"""
class SMSmessageStatus(Enum):
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


def convert_smsmessagestatus(s): return SMSmessageStatus(int(s))
sqlite3.enable_callback_tracebacks(True)
sqlite3.register_converter("smsmessagestatus", convert_smsmessagestatus)
sqlite3.register_adapter(SMSmessageStatus,  SMSmessageStatus.adapt_smsmessagestatus)

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
        mm = self.find(gateway=gws, status=SMSmessageStatus.QUEUED, _verbose=_verbose)  # Look for queued on any of gateways
        if mm:
            return mm[0] if mm else None
        mm = self.find(gateway=gws, status=SMSmessageStatus.FAILED, _verbose=_verbose)  # Look for failed and retry
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

class SMSrelay():   # Encapsulation of class methods that define this
    dispatcher = None       # Set to class to dispatch messages to

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
            msg.update(status=SMSmessageStatus.GATEWAY)
            msg.update(status=SMSmessageStatus.SENT)  # Simulate sent TODO replace with response from gateway that sent
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
        kwargs["phonenumber"] = kwargs["from"]    # SMSmessage uses phonenumber for both incoming and outgoing
        del(kwargs["from"])
        gws = SMSgateways.findOrCreateAndUpdate(device_id=kwargs.get("device_id"), phonenumber=kwargs.get("sent_to"))
        gw = gws[0] # Should always be just 1
        gw.update(lastincoming=timestamp())
        del(kwargs["sent_to"])  # Dont store on message, use gw
        del(kwargs["device_id"])  # Dont store on message, use gw
        msg = SMSmessage.insert(gateway=gw, status=SMSmessageStatus.INCOMING, **kwargs)
        if msg._isloop:
            msg.update(status=SMSmessageStatus.LOOP)
        else:
            # Send it the app
            response = cls.dispatcher.dispatch(msg=msg, gateway=gws)
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
        kwargs["status"] = SMSmessageStatus.QUEUED
        return SMSmessage.insert(**kwargs)

class SMSdispatcher(object):
    spam = [ "BUY ONE",]
    patterns = []

    @classmethod
    def isspam(cls, message):   # Checking spam is a method of the dispatcher as may be language or context dependent
        return any([sp in message.message for sp in cls.spam])

    @classmethod
    def update(self, **kwargs):
        self.patterns.append(kwargs)    # Append kwargs as a dict

    @classmethod
    def dispatch(cls, msg, gateway, **kwargs ):
        if cls.isspam(msg):
            msg.update(status=SMSmessageStatus.SPAM)
            return None
        #TODO clever dispatching matching patterns
        #TODO clever dispatching matching regexps
        for p in cls.patterns:
            for s in p["strings"]:
                if s in msg.message:
                    return p.f(msg)

class TestDispatcher(SMSdispatcher):

    def thank(self, msg):
        return { "phonenumber": msg.phonenumber, "message": "Thanks a bunch" }

TestDispatcher.update(strings = ["hello","bonjour"], f=TestDispatcher.thank )


def test():
    from sqlitewrap import SqliteWrap
    # Create table
    SqliteWrap.setdb("smsmessagetest.db")
    SqliteWrap.db.connect()
    try:
        SMSmessage.createtable(dropfirst=True)    # ONLY WORKS ONCE
        SMSgateway.createtable(dropfirst=True)    # ONLY WORKS ONCE
    except sqlite3.OperationalError as e:
        print e
    print "Testing SMS Relay"
    SMSrelay.dispatcher=TestDispatcher  # Setup for testing
    assert SMSmessageStatus.QUEUED.name == "QUEUED", "Check enumerations loading correctly"
    assert isinstance(SMSmessageStatus.QUEUED, SMSmessageStatus), "Should be an instance if want conform to work"
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
    resp = SMSrelay.sms_incoming(**{'timestamp': u'2017-02-08T05:37:06Z', 'message': u'lala', 'from': u'+16177179014',
                                    'sent_to': u'+14159969138', 'device_id': u'1007', 'message_id': u'100001'})
    assert len(SMSgateways.all()) == 1
    # Should queue a message "Thanks a bunch"
    resp = SMSrelay.sms_poll(_verbose=False, **{'battery_strength': u'50', 'timestamp': u'2017-02-07T06:28Z', 'wifi_strength': u'0', 'gsm_strength': u'[38]',
           'charging': u'true', 'device_id': u'1007', 'sim_num': u'[14159969138]'})
    assert len(SMSgateways.all()) == 1
    print "XXX@246",resp
    assert resp["message"] == "Thanks a bunch", "Should be respone from TestDispatcher"
    # Test loops
    resp = SMSrelay.sms_incoming(**{'timestamp': u'2017-02-08T05:37:06Z', 'message': u'lala', 'from': u'+16177179014',
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
