# slappyengine.iso — API Reference

> Auto-generated. Re-run `python scripts/gen_subpackage_api_docs.py`.
> Do not hand-edit — every entry below comes from runtime introspection
> (`inspect.signature`, `inspect.getdoc`, `dataclasses.fields`).


SlapPyEngine.iso — Isometric 2D-grid-with-Z rendering subsystem.

## Classes

### `IsoCamera`

_class — defined in `slappyengine.iso.iso_camera`_

Camera for isometric scenes.

#### Constructor signature

```python
IsoCamera(viewpoint: 'IsoViewpoint' = <IsoViewpoint.NE: 0>, tile_w: 'int' = 64, tile_h: 'int' = 32) -> 'None'
```

#### Methods

- `pan(self, dx: 'float', dy: 'float') -> 'None'` — Shift the camera by (dx, dy) pixels.
- `reset_pan(self) -> 'None'` — Return the camera to the grid origin.
- `rotate_ccw(self) -> 'IsoViewpoint'` — Rotate the viewpoint 90° counter-clockwise and return the new viewpoint.
- `rotate_cw(self) -> 'IsoViewpoint'` — Rotate the viewpoint 90° clockwise and return the new viewpoint.
- `screen_to_grid(self, sx: 'float', sy: 'float', screen_w: 'int' = 1280, screen_h: 'int' = 720) -> 'tuple[int, int]'` — Convert a mouse/screen pixel position to grid (gx, gy) at gz=0.
- `set_viewpoint(self, vp: 'IsoViewpoint') -> 'None'` — Directly set the active viewpoint.
- `update_entity_viewpoints(self, entities: 'list') -> 'None'` — Sync all entity rotations to the current camera viewpoint.

### `IsoCell`

_dataclass — defined in `slappyengine.iso.iso_grid`_

One cell in the 3D isometric grid.

#### Constructor signature

```python
IsoCell(gx: 'int', gy: 'int', gz: 'int', tile_def: 'IsoTileDef | None' = None, entity: 'Any' = None, z_offset: 'float' = 0.0) -> None
```

#### Fields

- `entity: Any` — default `None`
- `gx: int`
- `gy: int`
- `gz: int`
- `tile_def: IsoTileDef | None` — default `None`
- `z_offset: float` — default `0.0`

### `IsoEntity`

_dataclass — defined in `slappyengine.iso.iso_entity`_

An entity positioned in the isometric grid.

#### Constructor signature

```python
IsoEntity(grid_x: 'float' = 0.0, grid_y: 'float' = 0.0, grid_z: 'float' = 0.0, local_z: 'float' = 0.0, facing_angle: 'float' = 0.0, receives_fluid_forces: 'bool' = False) -> None
```

#### Fields

- `facing_angle: float` — default `0.0`
- `grid_x: float` — default `0.0`
- `grid_y: float` — default `0.0`
- `grid_z: float` — default `0.0`
- `local_z: float` — default `0.0`
- `receives_fluid_forces: bool` — default `False`

#### Methods

- `distance_to(self, other: "'IsoEntity'") -> 'float'` — Return the Euclidean grid distance to *other* (ignoring Z).
- `face_toward(self, target_gx: 'float', target_gy: 'float') -> 'None'` — Set :attr:`facing_angle` toward a target grid position.
- `move_by(self, dgx: 'float', dgy: 'float', dgz: 'float' = 0.0) -> 'None'` — Displace the entity by (dgx, dgy, dgz) grid units.
- `move_to(self, gx: 'float', gy: 'float', gz: 'float' = 0.0) -> 'None'` — Teleport the entity to grid position (gx, gy, gz).

### `IsoGrid`

_class — defined in `slappyengine.iso.iso_grid`_

3D grid of :class:`IsoCell` objects with depth sorting.

#### Constructor signature

```python
IsoGrid(width: 'int', height: 'int', depth: 'int' = 8, tile_w: 'int' = 64, tile_h: 'int' = 32, z_scale: 'float' = 16.0) -> 'None'
```

#### Methods

- `all_cells(self) -> 'list[IsoCell]'` — Return all non-empty cells in arbitrary order.
- `get_cell(self, gx: 'int', gy: 'int', gz: 'int') -> 'IsoCell | None'` — Return the cell at (gx, gy, gz), or ``None`` if empty.
- `remove_tile(self, gx: 'int', gy: 'int', gz: 'int') -> 'None'` — Remove the cell at (gx, gy, gz) if it exists.
- `set_tile(self, gx: 'int', gy: 'int', gz: 'int', tile_def: 'IsoTileDef') -> 'IsoCell'` — Place *tile_def* at grid position (gx, gy, gz).
- `sorted_cells(self, vp: 'IsoViewpoint', cam_x: 'float' = 0.0, cam_y: 'float' = 0.0, screen_w: 'int' = 1280, screen_h: 'int' = 720) -> 'list[tuple[IsoCell, float, float]]'` — Return cells sorted back-to-front for painter's-algorithm rendering.
- `top_z(self, gx: 'int', gy: 'int') -> 'int'` — Return the highest occupied gz at column (gx, gy), or 0 if empty.
- `world_to_screen(self, gx: 'float', gy: 'float', gz: 'float', vp: 'IsoViewpoint', cam_x: 'float' = 0.0, cam_y: 'float' = 0.0) -> 'tuple[float, float]'` — Project grid coordinates to screen space.

### `IsoScene`

_class — defined in `slappyengine.iso.iso_scene`_

An isometric scene that integrates with the SlapPyEngine scene system.

#### Constructor signature

```python
IsoScene(grid_w: 'int' = 20, grid_h: 'int' = 20, grid_d: 'int' = 4, tile_w: 'int' = 64, tile_h: 'int' = 32, z_scale: 'float' = 16.0, viewpoint: 'IsoViewpoint' = <IsoViewpoint.NE: 0>) -> 'None'
```

#### Methods

- `add_iso_entity(self, entity: 'IsoEntity') -> 'None'` — Register an :class:`IsoEntity` with this scene.
- `add_z_layer(self, layer: 'Any') -> 'None'`
- `remove_iso_entity(self, entity: 'IsoEntity') -> 'None'` — Remove an :class:`IsoEntity` from this scene.
- `remove_z_layer(self, layer: 'Any') -> 'None'`
- `sorted_render_list(self, screen_w: 'int' = 1280, screen_h: 'int' = 720) -> 'list[dict[str, Any]]'` — Return tiles and entities interleaved in painter's-algorithm order.
- `update(self, dt: 'float') -> 'None'` — Tick the scene.

### `IsoTileDef`

_dataclass — defined in `slappyengine.iso.iso_grid`_

Visual definition for a tile type.

#### Constructor signature

```python
IsoTileDef(name: 'str', sprite_path: 'str', sprite_paths: 'dict[IsoViewpoint, str]' = <factory>, z_height: 'float' = 0.0, passable: 'bool' = True, color: 'tuple[int, int, int]' = (128, 128, 128)) -> None
```

#### Fields

- `color: tuple[int, int, int]` — default `(128, 128, 128)`
- `name: str`
- `passable: bool` — default `True`
- `sprite_path: str`
- `sprite_paths: dict[IsoViewpoint, str]` — default factory
- `z_height: float` — default `0.0`

#### Methods

- `sprite_for(self, vp: 'IsoViewpoint') -> 'str'` — Return the best sprite path for the given viewpoint.

### `IsoViewpoint`

_class — defined in `slappyengine.iso.projection`_

Enum where members are also (and must be) ints

#### Constructor signature

```python
IsoViewpoint(*values)
```

## Functions

_(none)_

## Constants

_(none)_

## Inner modules

- `slappyengine.iso.combat`
- `slappyengine.iso.iso_camera`
- `slappyengine.iso.iso_entity`
- `slappyengine.iso.iso_grid`
- `slappyengine.iso.iso_scene`
- `slappyengine.iso.projection`
