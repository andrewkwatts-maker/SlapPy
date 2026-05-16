pub mod physics {
    use pyo3::prelude::*;
    use rayon::prelude::*;
    use std::collections::HashMap;

    // -------------------------------------------------------------------------
    // BodyType
    // -------------------------------------------------------------------------

    #[pyclass(eq, eq_int)]
    #[derive(Clone, Copy, PartialEq)]
    pub enum BodyType {
        Dynamic   = 0,
        Kinematic = 1,
        Static    = 2,
    }

    // -------------------------------------------------------------------------
    // InternalBody  (not exposed to Python — lives inside PhysicsWorld)
    // -------------------------------------------------------------------------

    struct InternalBody {
        position:    [f32; 3],
        velocity:    [f32; 3],
        orientation: [f32; 4],
        angular_vel: [f32; 3],
        mass:        f32,
        restitution: f32,
        friction:    f32,
        body_type:   BodyType,
        handle:      u32,
    }

    impl InternalBody {
        fn from_rigid(b: &RigidBody) -> Self {
            InternalBody {
                position:    b.position,
                velocity:    b.velocity,
                orientation: b.orientation,
                angular_vel: b.angular_vel,
                mass:        b.mass,
                restitution: b.restitution,
                friction:    b.friction,
                body_type:   b.body_type,
                handle:      b.handle,
            }
        }

        fn is_static(&self) -> bool {
            self.mass == 0.0 || self.body_type == BodyType::Static
        }

        /// Symplectic Euler integration.
        fn integrate(&mut self, gx: f32, gy: f32, gz: f32, dt: f32) {
            if self.is_static() || self.body_type == BodyType::Kinematic {
                return;
            }
            self.velocity[0] += gx * dt;
            self.velocity[1] += gy * dt;
            self.velocity[2] += gz * dt;
            self.position[0] += self.velocity[0] * dt;
            self.position[1] += self.velocity[1] * dt;
            self.position[2] += self.velocity[2] * dt;
        }

        /// AABB half-extents are 0.5 (unit cube) on each axis.
        fn aabb_min(&self) -> [f32; 3] {
            [
                self.position[0] - 0.5,
                self.position[1] - 0.5,
                self.position[2] - 0.5,
            ]
        }

        fn aabb_max(&self) -> [f32; 3] {
            [
                self.position[0] + 0.5,
                self.position[1] + 0.5,
                self.position[2] + 0.5,
            ]
        }
    }

    // -------------------------------------------------------------------------
    // RigidBody  (Python-facing; used for construction / query)
    // -------------------------------------------------------------------------

    #[pyclass]
    pub struct RigidBody {
        pub position:    [f32; 3],
        pub velocity:    [f32; 3],
        pub orientation: [f32; 4],  // xyzw
        pub angular_vel: [f32; 3],
        pub mass:        f32,
        pub restitution: f32,
        pub friction:    f32,
        pub body_type:   BodyType,
        pub handle:      u32,
    }

    #[pymethods]
    impl RigidBody {
        #[new]
        pub fn new(mass: f32) -> Self {
            RigidBody {
                position:    [0.0, 0.0, 0.0],
                velocity:    [0.0, 0.0, 0.0],
                orientation: [0.0, 0.0, 0.0, 1.0],
                angular_vel: [0.0, 0.0, 0.0],
                mass,
                restitution: 0.5,
                friction:    0.5,
                body_type:   if mass == 0.0 { BodyType::Static } else { BodyType::Dynamic },
                handle:      0,
            }
        }

        pub fn set_position(&mut self, x: f32, y: f32, z: f32) {
            self.position = [x, y, z];
        }

        pub fn get_position(&self) -> (f32, f32, f32) {
            (self.position[0], self.position[1], self.position[2])
        }

        pub fn set_velocity(&mut self, vx: f32, vy: f32, vz: f32) {
            self.velocity = [vx, vy, vz];
        }

        pub fn get_velocity(&self) -> (f32, f32, f32) {
            (self.velocity[0], self.velocity[1], self.velocity[2])
        }

        /// Accumulate a force over dt into velocity (F = ma → Δv = (F/m)*dt).
        pub fn apply_force(&mut self, fx: f32, fy: f32, fz: f32, dt: f32) {
            if self.mass == 0.0 {
                return;
            }
            let inv_m = 1.0 / self.mass;
            self.velocity[0] += fx * inv_m * dt;
            self.velocity[1] += fy * inv_m * dt;
            self.velocity[2] += fz * inv_m * dt;
        }

        /// Apply an instantaneous impulse (Δv = I/m).
        pub fn apply_impulse(&mut self, ix: f32, iy: f32, iz: f32) {
            if self.mass == 0.0 {
                return;
            }
            let inv_m = 1.0 / self.mass;
            self.velocity[0] += ix * inv_m;
            self.velocity[1] += iy * inv_m;
            self.velocity[2] += iz * inv_m;
        }

        pub fn is_static(&self) -> bool {
            self.mass == 0.0 || self.body_type == BodyType::Static
        }

        /// Integrate position and velocity for one timestep (symplectic Euler).
        pub fn integrate(&mut self, gx: f32, gy: f32, gz: f32, dt: f32) {
            if self.is_static() || self.body_type == BodyType::Kinematic {
                return;
            }
            self.velocity[0] += gx * dt;
            self.velocity[1] += gy * dt;
            self.velocity[2] += gz * dt;
            self.position[0] += self.velocity[0] * dt;
            self.position[1] += self.velocity[1] * dt;
            self.position[2] += self.velocity[2] * dt;
        }

        pub fn __repr__(&self) -> String {
            format!(
                "RigidBody(handle={}, pos=({:.3},{:.3},{:.3}), mass={:.3})",
                self.handle,
                self.position[0], self.position[1], self.position[2],
                self.mass,
            )
        }
    }

    // -------------------------------------------------------------------------
    // Broad-phase helpers
    // -------------------------------------------------------------------------

    fn aabbs_overlap(a_min: &[f32; 3], a_max: &[f32; 3], b_min: &[f32; 3], b_max: &[f32; 3]) -> bool {
        a_min[0] <= b_max[0] && a_max[0] >= b_min[0]
            && a_min[1] <= b_max[1] && a_max[1] >= b_min[1]
            && a_min[2] <= b_max[2] && a_max[2] >= b_min[2]
    }

    /// Ray–AABB intersection (slab method). Returns Some(t) at entry if hit, else None.
    fn ray_aabb(
        ox: f32, oy: f32, oz: f32,
        dx: f32, dy: f32, dz: f32,
        mn: &[f32; 3], mx: &[f32; 3],
    ) -> Option<f32> {
        let mut t_min = f32::NEG_INFINITY;
        let mut t_max = f32::INFINITY;

        for axis in 0..3 {
            let (o, d, lo, hi) = match axis {
                0 => (ox, dx, mn[0], mx[0]),
                1 => (oy, dy, mn[1], mx[1]),
                _ => (oz, dz, mn[2], mx[2]),
            };
            if d.abs() < 1e-8 {
                if o < lo || o > hi {
                    return None;
                }
            } else {
                let inv = 1.0 / d;
                let t1 = (lo - o) * inv;
                let t2 = (hi - o) * inv;
                let (t1, t2) = if t1 < t2 { (t1, t2) } else { (t2, t1) };
                t_min = t_min.max(t1);
                t_max = t_max.min(t2);
                if t_min > t_max {
                    return None;
                }
            }
        }

        if t_max < 0.0 {
            return None;
        }
        Some(if t_min >= 0.0 { t_min } else { t_max })
    }

    // -------------------------------------------------------------------------
    // PhysicsWorld
    // -------------------------------------------------------------------------

    #[pyclass]
    pub struct PhysicsWorld {
        bodies:      Vec<InternalBody>,
        handle_map:  HashMap<u32, usize>,   // handle → index in `bodies`
        next_id:     u32,
        gravity:     [f32; 3],
    }

    #[pymethods]
    impl PhysicsWorld {
        #[new]
        pub fn new() -> Self {
            PhysicsWorld {
                bodies:     Vec::new(),
                handle_map: HashMap::new(),
                next_id:    1,
                gravity:    [0.0, -980.0, 0.0],
            }
        }

        pub fn set_gravity(&mut self, gx: f32, gy: f32, gz: f32) {
            self.gravity = [gx, gy, gz];
        }

        /// Add a body to the world and return its handle.
        pub fn add_body(&mut self, body: &RigidBody) -> u32 {
            let handle = self.next_id;
            self.next_id += 1;
            let mut internal = InternalBody::from_rigid(body);
            internal.handle = handle;
            let idx = self.bodies.len();
            self.bodies.push(internal);
            self.handle_map.insert(handle, idx);
            handle
        }

        /// Remove a body by handle. Uses swap-remove to keep the Vec dense.
        pub fn remove_body(&mut self, handle: u32) {
            let Some(&idx) = self.handle_map.get(&handle) else { return };
            self.handle_map.remove(&handle);
            let last_handle = self.bodies.last().map(|b| b.handle);
            self.bodies.swap_remove(idx);
            if let Some(lh) = last_handle {
                if lh != handle {
                    self.handle_map.insert(lh, idx);
                }
            }
        }

        /// Step the simulation: integrate dynamics, then broad-phase AABB collision detection.
        /// Returns (handle_a, handle_b) pairs whose AABBs overlap this step.
        pub fn step(&mut self, dt: f32) -> Vec<(u32, u32)> {
            let [gx, gy, gz] = self.gravity;

            // Parallel integration over dynamic bodies.
            self.bodies
                .par_iter_mut()
                .for_each(|b| b.integrate(gx, gy, gz, dt));

            // O(n²) broad-phase — BVH upgrade deferred to a future sprint.
            let n = self.bodies.len();
            let mut pairs: Vec<(u32, u32)> = Vec::new();

            for i in 0..n {
                for j in (i + 1)..n {
                    let a_min = self.bodies[i].aabb_min();
                    let a_max = self.bodies[i].aabb_max();
                    let b_min = self.bodies[j].aabb_min();
                    let b_max = self.bodies[j].aabb_max();
                    if aabbs_overlap(&a_min, &a_max, &b_min, &b_max) {
                        pairs.push((self.bodies[i].handle, self.bodies[j].handle));
                    }
                }
            }

            pairs
        }

        pub fn body_count(&self) -> usize {
            self.bodies.len()
        }

        pub fn get_position(&self, handle: u32) -> Option<(f32, f32, f32)> {
            self.handle_map.get(&handle).map(|&idx| {
                let p = &self.bodies[idx].position;
                (p[0], p[1], p[2])
            })
        }

        pub fn set_position(&mut self, handle: u32, x: f32, y: f32, z: f32) {
            if let Some(&idx) = self.handle_map.get(&handle) {
                self.bodies[idx].position = [x, y, z];
            }
        }

        /// Raycast against all body AABBs.
        /// Returns (handle, distance) pairs sorted nearest-first.
        pub fn raycast(
            &self,
            ox: f32, oy: f32, oz: f32,
            dx: f32, dy: f32, dz: f32,
        ) -> Vec<(u32, f32)> {
            let mut hits: Vec<(u32, f32)> = self
                .bodies
                .iter()
                .filter_map(|b| {
                    let mn = b.aabb_min();
                    let mx = b.aabb_max();
                    ray_aabb(ox, oy, oz, dx, dy, dz, &mn, &mx)
                        .map(|t| (b.handle, t))
                })
                .collect();
            hits.sort_by(|a, b| a.1.partial_cmp(&b.1).unwrap_or(std::cmp::Ordering::Equal));
            hits
        }

        pub fn __repr__(&self) -> String {
            format!(
                "PhysicsWorld(bodies={}, gravity=({:.1},{:.1},{:.1}))",
                self.bodies.len(),
                self.gravity[0], self.gravity[1], self.gravity[2],
            )
        }
    }

    // -------------------------------------------------------------------------
    // Module registration
    // -------------------------------------------------------------------------

    pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
        m.add_class::<BodyType>()?;
        m.add_class::<RigidBody>()?;
        m.add_class::<PhysicsWorld>()?;
        Ok(())
    }
}

// lib.rs: add `mod physics;` and `physics::physics::register(m)?`
