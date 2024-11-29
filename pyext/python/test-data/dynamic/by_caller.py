def import_by_name(name):
    __import__(f"dynamic._{name}")


class Importer:
    def by_name(self, name):
        if name:
            import_by_name(name)


importer = Importer()
