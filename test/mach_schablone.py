import FreeCAD as App, Part, os
out = os.path.expanduser("~/laserwerk/test")
doc = App.newDocument("Schablone")
V = App.Vector
aussen = Part.makePolygon([V(0,0,0),V(60,0,0),V(60,40,0),V(0,40,0),V(0,0,0)])
loch = Part.Wire(Part.makeCircle(5, V(20,20,0)))
schlitz = Part.makePolygon([V(38,12,0),V(52,12,0),V(52,18,0),V(38,18,0),V(38,12,0)])
face = Part.Face([aussen, loch, schlitz])
obj = doc.addObject("Part::Feature", "Schablone"); obj.Shape = face
doc.recompute()
try:
    import importSVG; importSVG.export([obj], os.path.join(out, "schablone.svg")); print("SVG ok")
except Exception as e: print("SVG Fehler:", e)
try:
    import importDXF; importDXF.export([obj], os.path.join(out, "schablone.dxf")); print("DXF ok")
except Exception as e: print("DXF Fehler:", e)
