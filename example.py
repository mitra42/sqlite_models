# encoding: utf-8
import sqlite3
from model import Model, Models
from json import loads, dumps
from datetime import datetime
from decimal import Decimal
from model_exceptions import ModelExceptionRecordNotFound, ModelExceptionInvalidTag, ModelExceptionCantFind

class ModelExample(Model):
    _tablename = "modelexample"
    _createsql = "CREATE TABLE %s (id integer primary key, name text, father modelexample, siblings modelexamples, " \
                 "kitty Decimal, parms json, lastmod timestamp, tags tags)"
    _insertsql = "INSERT INTO %s VALUES (NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL)"
    _validtags = {"FOO"}
    _parmfields = {"pfield1": unicode, "pfield2": int, "mother": None, "change": Decimal, "parmstime": datetime, "parmsmodels": None}

ModelExample._parmfields["mother"]=ModelExample # Because undefined when defining _parmfields above

def convert_modelexample(s):
    # Note s is never None or Null etc, that skips the conversion and returns None
    return ModelExample(s)

sqlite3.register_converter("modelexample", convert_modelexample)  # Return JSON, could be dict or list


class ModelExamples(Models):
    _parentclass = ModelExample

ModelExample._parmfields["parmsmodels"]=ModelExamples   # Done here as undefined during definition of ModelExample

def convert_modelexamples(s):
    return ModelExamples(loads(s))

sqlite3.register_converter("modelexamples", convert_modelexamples)  # Return JSON, could be dict or list

# ==== Support DECIMAL type ====
from decimal import Decimal
# This is an example of adding support for the decimal class in both parms fields and columns (See !ADD-TYPE)
Model.add_supportedclass(Decimal,
               #parms2attr=lambda s: Decimal(s), # Not required since its constructor works
               attr2parms=unicode,              # Convert a datetime to a storable string
               )
sqlite3.register_adapter(Decimal,unicode)
sqlite3.register_converter("decimal",Decimal)
# =======

def test():
    from sqlitewrap import SqliteWrap
    # Create table
    SqliteWrap.setdb("test.db")
    SqliteWrap.db.connect()
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
    now = datetime.now()
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
    # Test supported type Decimal which is stored as a strong to preserve decimal places
    bar.update(change=Decimal("123.456"))
    assert ModelExample(1).change == Decimal("123.456")
    bar.update(kitty=Decimal("123.456"))
    assert ModelExample(1).kitty == Decimal("123.456")
    # Note cant do arithmetic "finds" on Decimal since stored as a precise string.
    # Test find
    assert len(ModelExamples.find(name="Brian")) == 1, "Should find one record"
    assert ModelExample.find(name="Brian") == brother, "Should find the brother record"
    assert ModelExample.find(name="Xyz") is None, "Cant find it"
    try:
        ModelExample.find(name="Xyz",_nullerr=ModelExceptionCantFind) is None, "Cant find it"
    except ModelExceptionCantFind as e:
        pass
    else:
        assert False,"Should throw ModelExceptionCantFind"
    #---
    assert len(ModelExamples.all()) == 4
    bar.delete()
    assert len(ModelExamples.all()) == 3

    SqliteWrap.db.disconnect()