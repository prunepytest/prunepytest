from .. import by_caller

def all():
    by_caller.importer.by_name("foo")
    by_caller.importer.by_name("bar")
    by_caller.importer.by_name("baz")
