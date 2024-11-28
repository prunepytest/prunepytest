import os.path
from traceback import extract_stack

def import_by_caller():
    __import__(f'dynamic._{os.path.basename(extract_stack()[-2].filename)[:-3]}')
