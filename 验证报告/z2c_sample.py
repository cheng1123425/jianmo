import cadquery as cq

plate_length = 60.0
plate_width = 40.0
plate_thickness = 8.0
rib_length = 20.0
rib_width = 6.0
hole_diameter = 8.0
mount_hole_dia = 3.0
mount_hole_offset = 5.0
fillet_radius = 2.0
chamfer_distance = 1.0
slot_width = 4.0
slot_length = 30.0

base = (
    cq.Workplane('XY')
    .rect(plate_length, plate_width, centered=True)
    .extrude(plate_thickness)
)
base = base.edges("|Z").fillet(fillet_radius)

rib = (
    cq.Workplane('XY')
    .center(-plate_length/2 + rib_length/2, 0)
    .rect(rib_length, rib_width, centered=True)
    .extrude(plate_thickness)
)
bracket = base.union(rib)

bracket = bracket.cut(
    cq.Workplane('XY').center(0, 0).circle(hole_diameter/2).extrude(plate_thickness + 2)
)

slot = (
    cq.Workplane('XY')
    .center(plate_length/2 - slot_length/2, 0)
    .rect(slot_length, slot_width, centered=True)
    .extrude(plate_thickness)
)
bracket = bracket.cut(slot)

mount_positions = [
    (-plate_length/2 + mount_hole_offset, -plate_width/2 + mount_hole_offset),
    (-plate_length/2 + mount_hole_offset, plate_width/2 - mount_hole_offset),
    (plate_length/2 - mount_hole_offset, -plate_width/2 + mount_hole_offset),
    (plate_length/2 - mount_hole_offset, plate_width/2 - mount_hole_offset),
]
for x, y in mount_positions:
    bracket = bracket.cut(
        cq.Workplane('XY').center(x, y).circle(mount_hole_dia/2).extrude(plate_thickness + 2)
    )

bracket = bracket.edges("|Z").chamfer(chamfer_distance)
result = bracket
