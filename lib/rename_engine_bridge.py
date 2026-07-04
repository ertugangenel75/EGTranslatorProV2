
# -*- coding: utf-8 -*-
from Autodesk.Revit.DB import *

class LoadOpts(IFamilyLoadOptions):
    def OnFamilyFound(self, a, b):
        b.Value = True
        return True
    def OnSharedFamilyFound(self, a, b, c, d):
        d.Value = True
        return True

def reload_family(doc, fdoc, name):
    import tempfile, os, re
    safe = re.sub(r'[^\w]', '_', name)[:40]
    tmp = os.path.join(tempfile.gettempdir(), safe + "_v25.rfa")

    opt = SaveAsOptions()
    opt.OverwriteExistingFile = True
    fdoc.SaveAs(tmp, opt)
    fdoc.Close(False)

    t = Transaction(doc, "Reload Family v2.5")
    t.Start()
    doc.LoadFamily(tmp, LoadOpts())
    t.Commit()

    try: os.remove(tmp)
    except: pass
