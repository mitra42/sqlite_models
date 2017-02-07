# encoding: utf-8
# import with ...
# from model_exceptions import (ModelExceptionRecordNotFound, ModelExceptionUpdateFailure, ModelExceptionInvalidTag,
#       ModelExceptionInvalidTag, ModelExceptionRecordTooMany, ModelExceptionCantFind)

class ModelException(Exception):
    """
    Base class for Exceptions
    errno   Number of error,
    msg     Parameterised string for message
    msgargs Arguments that slot into msg
    __str__ Returns msg expanded with msgparms
    """
    errno=0
    msg="Generic Model Exception"
    def __init__(self, **kwargs):
        self.msgargs=kwargs # Store arbitrary dict of message args (can be used ot output msg from template

    def __str__(self):
        try:
            return self.msg.format(**self.msgargs)
        except:
            return self.msg+" "+unicode(self.msgargs)

class ModelExceptionRecordNotFound(ModelException):
    errno=2
    msg=u"Record {table} {id} Not Found"

class ModelExceptionUpdateFailure (ModelException):
    errno=9002
    msg=u"Failed to update sql={sql}, values={valuestring}"

class ModelExceptionInvalidTag (ModelException):
    errno=9003
    msg=u"Invalid tag {tags} for {table} which allows {validtags}"

class ModelExceptionRecordTooMany(ModelException):
    errno=9004
    msg=u"Too many {table} found for {where}"

class ModelExceptionCantFind(ModelException):
    errno=9004
    msg=u"Can't find any {table} where {where}"
