A simple model architecture for sqlite
======================================

This package is intended to allow for simply creating sqlite applications in Python

 - open source sqlite wrapper
 - Simpler than Django
 - Support for common Python types like Decimal
 - Easily extended to cover new data types
 - Efficiently use the database
 - Compatible with running under cherrypy, but not dependent on it.

Objects are accessed via their attributes (as with Django).
e.g. at its simplest ``obj.name``  will return the name column from the table.

Objects are added via insert e.g.
obj.insert(name="Fred", age=10)

Objects are changed via a single function e.g. ``obj.update(name="Smith")`` will update the object and its representation
in the database.

Objects can be retrieved via a comprehensive find e.g.
find(name="Fred") or find("name="Fred", age="> 10")

An object can be created without loading from the database allowing for easy references.
These are loaded only when one of the attributes is referenced.
e.g. ``obj=Obj(1)`` will create an instance of Obj, and obj.name will read row 1 of the database.

Adding a new table is a simple process, but requires a little knowledge of SQL See examples.py for a comprehensive example.

Two objects compare if their id's are the same: i.e.
  ``pete=Person(1), bro=Person(1), pete == bro``

Special fields
~~~~~~~~~~~~~~~
parms
  Holds a json formated set of fields supporting slightly less functionality, but easier to add and remove.
tags
  Holds a list of strings that are like boolena fields
lastmod
  Will be updated to the current time when the object is changed if _lastmodfield defined.

HOWTO
------
Define a table:
~~~~~~~~~~~~~~~~
A table is defined via a pair of classes - for the singular and plural case.
See example.py. ModelExample, and ModelExamples

For each table, will need to define:

    _tablename = "family"
        Name of the sql table to store it in
    _createsql = "CREATE TABLE %s (id integer primary key, name text, ..., parms json, lastmod timestamp, tags tags)"
        SQL creation string, specifies types of fields stored
    _insertsql = "INSERT INTO %s VALUES (NULL, NULL, NULL, NULL, NULL, NULL, NULL)"
        SQL insertion string for a blank object (one NULL per column)
    _validtags = {"FOO"}
        If there is a tags field, a set of the tags that are allowed
    _parmfields = {"pfield1": unicode, "pfield2": int, "mother": Person, "siblings": Persons}
        If there is a parms field, a dictionary of the parm names and classes, if this is recursive, then
        use "None" as the class and store to it immediately after the class is defined
    _lastmodfield = "lastmod"
        Ensure the lastmod field is updated when record is created or modified.

The rest of the definition of a table is boiler plate,
note that the _parmfields will need to be edited if it is self-referential (see the example)

Add support for a class to be stored in fields of the database.
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
See ``!ADD-TYPE`` in the code. Will need to define functions for converting attributes to something that can be converted to JSON and vica-versa
Register these functions with Model.add_supportedclass(class, {"parms2attr": ..., "attr2parms": ...})
If they are to be stored in columns, use sqlite3.register_adapter or __conform__ and sqlite3.register_converter
