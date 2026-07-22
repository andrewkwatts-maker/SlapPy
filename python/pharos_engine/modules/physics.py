from pharos_engine.struct_registry import StructModule

class PhysicsModule(StructModule):
    name = "physics"
    channels = [
        ("strength",   "f32"),   # tensile strength
        ("stiffness",  "f32"),   # Young's modulus proxy
        ("density",    "f32"),   # mass per unit area
        ("vel_x",      "f32"),   # velocity x
        ("vel_y",      "f32"),   # velocity y
    ]
    compute_passes = ["rigid"]
    default_values = {
        "strength":  1.0,
        "stiffness": 1.0,
        "density":   1.0,
        "vel_x":     0.0,
        "vel_y":     0.0,
    }
