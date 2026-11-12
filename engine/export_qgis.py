"""Write a genuine QGIS project rather than incomplete hand-authored XML."""
from pathlib import Path
import os
import sys
from qgis.core import (
    QgsApplication, QgsProject, QgsRasterLayer, QgsCoordinateReferenceSystem,
    QgsReferencedRectangle, QgsRasterShader, QgsColorRampShader,
    QgsSingleBandPseudoColorRenderer, QgsVectorLayer, QgsFillSymbol, Qgis,
)
from qgis.PyQt.QtGui import QColor

folder = Path(sys.argv[1]).resolve()
app = QgsApplication([], False)
app.initQgis()
project = QgsProject()
layer = QgsRasterLayer(str(folder / "max_depth_m.tif"), "最大地表水深（公尺；情境）")
if not layer.isValid() or layer.crs().authid() != "EPSG:3826":
    raise RuntimeError("Export raster must load with EPSG:3826.")
crs = QgsCoordinateReferenceSystem("EPSG:3826")
project.setCrs(crs)
shader = QgsColorRampShader(0, .5)
shader.setColorRampType(QgsColorRampShader.Discrete)
shader.setColorRampItemList([
    QgsColorRampShader.ColorRampItem(v, QColor(color), label)
    for v, color, label in [
        (.01, "#102744", "≤1 cm"), (.05, "#255f88", "1–5 cm"),
        (.1, "#2998bb", "5–10 cm"), (.3, "#73cae1", "10–30 cm"),
        (.5, "#efb94d", "30–50 cm"), (float("inf"), "#e5654b", ">50 cm"),
    ]
])
raster_shader = QgsRasterShader()
raster_shader.setRasterShaderFunction(shader)
renderer = QgsSingleBandPseudoColorRenderer(layer.dataProvider(), 1, raster_shader)
renderer.setClassificationMin(0)
renderer.setClassificationMax(.5)
layer.setRenderer(renderer)
project.addMapLayer(layer)
boundary = QgsVectorLayer(str(folder / "xinyi_boundary.geojson"), "信義區界（白線內為統計範圍）", "ogr")
if not boundary.isValid() or boundary.crs().authid() != "EPSG:3826":
    raise RuntimeError("District boundary must load with EPSG:3826.")
boundary.renderer().setSymbol(QgsFillSymbol.createSimple({
    "color": "0,0,0,0", "outline_color": "237,239,241,255", "outline_width": "0.5",
    "style": "no",
}))
project.addMapLayer(boundary)
project.setTitle("信義區情境結果；非真實預報")
project.setBackgroundColor(QColor("#081f5c"))
project.viewSettings().setDefaultViewExtent(QgsReferencedRectangle(layer.extent(), crs))
project.setFilePathStorage(Qgis.FilePathType.Relative)
project.setFileName(str(folder / "result.qgs"))
if not project.write():
    raise RuntimeError("QGIS project write failed.")
print("QGIS_EXPORT_OK", flush=True)
os._exit(0)
