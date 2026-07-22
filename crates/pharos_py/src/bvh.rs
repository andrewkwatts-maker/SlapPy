#[cfg(feature = "3d")]
pub mod bvh {

    #[derive(Clone, Debug)]
    pub struct AABB {
        pub min: [f32; 3],
        pub max: [f32; 3],
    }

    impl AABB {
        pub fn new(min: [f32; 3], max: [f32; 3]) -> Self {
            Self { min, max }
        }

        pub fn empty() -> Self {
            Self {
                min: [f32::INFINITY; 3],
                max: [f32::NEG_INFINITY; 3],
            }
        }

        pub fn union(&self, other: &AABB) -> AABB {
            AABB {
                min: [
                    self.min[0].min(other.min[0]),
                    self.min[1].min(other.min[1]),
                    self.min[2].min(other.min[2]),
                ],
                max: [
                    self.max[0].max(other.max[0]),
                    self.max[1].max(other.max[1]),
                    self.max[2].max(other.max[2]),
                ],
            }
        }

        pub fn expand(&self, point: [f32; 3]) -> AABB {
            AABB {
                min: [
                    self.min[0].min(point[0]),
                    self.min[1].min(point[1]),
                    self.min[2].min(point[2]),
                ],
                max: [
                    self.max[0].max(point[0]),
                    self.max[1].max(point[1]),
                    self.max[2].max(point[2]),
                ],
            }
        }

        pub fn surface_area(&self) -> f32 {
            let dx = (self.max[0] - self.min[0]).max(0.0);
            let dy = (self.max[1] - self.min[1]).max(0.0);
            let dz = (self.max[2] - self.min[2]).max(0.0);
            2.0 * (dx * dy + dy * dz + dz * dx)
        }

        pub fn centroid(&self) -> [f32; 3] {
            [
                (self.min[0] + self.max[0]) * 0.5,
                (self.min[1] + self.max[1]) * 0.5,
                (self.min[2] + self.max[2]) * 0.5,
            ]
        }

        /// Returns the near-t of the intersection, or None if the ray misses.
        /// `inv_dir` must be `1.0 / dir` per component (caller's responsibility).
        pub fn intersect_ray(&self, origin: [f32; 3], inv_dir: [f32; 3]) -> Option<f32> {
            let mut t_min = f32::NEG_INFINITY;
            let mut t_max = f32::INFINITY;

            for i in 0..3 {
                let t0 = (self.min[i] - origin[i]) * inv_dir[i];
                let t1 = (self.max[i] - origin[i]) * inv_dir[i];
                let (lo, hi) = if t0 < t1 { (t0, t1) } else { (t1, t0) };
                t_min = t_min.max(lo);
                t_max = t_max.min(hi);
            }

            if t_max >= t_min && t_max >= 0.0 {
                Some(t_min.max(0.0))
            } else {
                None
            }
        }

        pub fn overlaps_sphere(&self, center: [f32; 3], radius: f32) -> bool {
            let mut dist_sq = 0.0f32;
            for i in 0..3 {
                let v = center[i];
                let delta = if v < self.min[i] {
                    self.min[i] - v
                } else if v > self.max[i] {
                    v - self.max[i]
                } else {
                    0.0
                };
                dist_sq += delta * delta;
            }
            dist_sq <= radius * radius
        }

        fn overlaps_aabb(&self, other: &AABB) -> bool {
            self.min[0] <= other.max[0]
                && self.max[0] >= other.min[0]
                && self.min[1] <= other.max[1]
                && self.max[1] >= other.min[1]
                && self.min[2] <= other.max[2]
                && self.max[2] >= other.min[2]
        }

        fn longest_axis(&self) -> usize {
            let dx = self.max[0] - self.min[0];
            let dy = self.max[1] - self.min[1];
            let dz = self.max[2] - self.min[2];
            if dx >= dy && dx >= dz {
                0
            } else if dy >= dz {
                1
            } else {
                2
            }
        }
    }

    // -------------------------------------------------------------------------

    pub struct BvhPrimitive {
        pub bounds: AABB,
        pub centroid: [f32; 3],
        pub user_index: u32,
    }

    pub struct BvhNode {
        pub bounds: AABB,
        pub left: u32,
        pub right: u32,
        pub first_prim: u32,
        pub prim_count: u32,
    }

    // -------------------------------------------------------------------------

    pub struct BVH {
        nodes: Vec<BvhNode>,
        prim_indices: Vec<u32>,
    }

    const NUM_BUCKETS: usize = 8;
    const MAX_LEAF_PRIMS: usize = 4;
    const C_TRAV: f32 = 1.0;

    impl BVH {
        pub fn build(prims: &[BvhPrimitive]) -> Self {
            if prims.is_empty() {
                return BVH {
                    nodes: Vec::new(),
                    prim_indices: Vec::new(),
                };
            }

            let mut indices: Vec<u32> = (0..prims.len() as u32).collect();
            let mut nodes: Vec<BvhNode> = Vec::with_capacity(prims.len() * 2);

            build_recursive(prims, &mut indices, &mut nodes, 0, prims.len());

            BVH {
                nodes,
                prim_indices: indices,
            }
        }

        pub fn query_ray(
            &self,
            prims: &[BvhPrimitive],
            origin: [f32; 3],
            dir: [f32; 3],
        ) -> Vec<u32> {
            let inv_dir = [
                if dir[0] != 0.0 { 1.0 / dir[0] } else { f32::INFINITY },
                if dir[1] != 0.0 { 1.0 / dir[1] } else { f32::INFINITY },
                if dir[2] != 0.0 { 1.0 / dir[2] } else { f32::INFINITY },
            ];

            let mut hits: Vec<(f32, u32)> = Vec::new();
            if !self.nodes.is_empty() {
                self.traverse_ray(prims, 0, origin, inv_dir, &mut hits);
            }
            hits.sort_unstable_by(|a, b| a.0.partial_cmp(&b.0).unwrap());
            hits.into_iter().map(|(_, idx)| idx).collect()
        }

        pub fn query_sphere(
            &self,
            prims: &[BvhPrimitive],
            center: [f32; 3],
            radius: f32,
        ) -> Vec<u32> {
            let mut result = Vec::new();
            if !self.nodes.is_empty() {
                self.traverse_sphere(prims, 0, center, radius, &mut result);
            }
            result
        }

        pub fn query_aabb(&self, prims: &[BvhPrimitive], bounds: &AABB) -> Vec<u32> {
            let mut result = Vec::new();
            if !self.nodes.is_empty() {
                self.traverse_aabb(prims, 0, bounds, &mut result);
            }
            result
        }

        pub fn node_count(&self) -> usize {
            self.nodes.len()
        }

        // -----------------------------------------------------------------
        // Private traversal helpers
        // -----------------------------------------------------------------

        fn traverse_ray(
            &self,
            prims: &[BvhPrimitive],
            node_idx: usize,
            origin: [f32; 3],
            inv_dir: [f32; 3],
            hits: &mut Vec<(f32, u32)>,
        ) {
            let node = &self.nodes[node_idx];
            if node.bounds.intersect_ray(origin, inv_dir).is_none() {
                return;
            }

            if node.prim_count > 0 {
                for i in 0..node.prim_count as usize {
                    let pi = self.prim_indices[node.first_prim as usize + i] as usize;
                    if let Some(t) = prims[pi].bounds.intersect_ray(origin, inv_dir) {
                        hits.push((t, prims[pi].user_index));
                    }
                }
            } else {
                self.traverse_ray(prims, node.left as usize, origin, inv_dir, hits);
                self.traverse_ray(prims, node.right as usize, origin, inv_dir, hits);
            }
        }

        fn traverse_sphere(
            &self,
            prims: &[BvhPrimitive],
            node_idx: usize,
            center: [f32; 3],
            radius: f32,
            result: &mut Vec<u32>,
        ) {
            let node = &self.nodes[node_idx];
            if !node.bounds.overlaps_sphere(center, radius) {
                return;
            }

            if node.prim_count > 0 {
                for i in 0..node.prim_count as usize {
                    let pi = self.prim_indices[node.first_prim as usize + i] as usize;
                    if prims[pi].bounds.overlaps_sphere(center, radius) {
                        result.push(prims[pi].user_index);
                    }
                }
            } else {
                self.traverse_sphere(prims, node.left as usize, center, radius, result);
                self.traverse_sphere(prims, node.right as usize, center, radius, result);
            }
        }

        fn traverse_aabb(
            &self,
            prims: &[BvhPrimitive],
            node_idx: usize,
            bounds: &AABB,
            result: &mut Vec<u32>,
        ) {
            let node = &self.nodes[node_idx];
            if !node.bounds.overlaps_aabb(bounds) {
                return;
            }

            if node.prim_count > 0 {
                for i in 0..node.prim_count as usize {
                    let pi = self.prim_indices[node.first_prim as usize + i] as usize;
                    if prims[pi].bounds.overlaps_aabb(bounds) {
                        result.push(prims[pi].user_index);
                    }
                }
            } else {
                self.traverse_aabb(prims, node.left as usize, bounds, result);
                self.traverse_aabb(prims, node.right as usize, bounds, result);
            }
        }
    }

    // -------------------------------------------------------------------------
    // SAH build — recursive, works on a mutable slice of `indices`
    // -------------------------------------------------------------------------

    fn build_recursive(
        prims: &[BvhPrimitive],
        indices: &mut Vec<u32>,
        nodes: &mut Vec<BvhNode>,
        start: usize,
        end: usize,
    ) -> usize {
        let node_idx = nodes.len();

        let prim_bounds = compute_prim_bounds(prims, indices, start, end);
        let count = end - start;

        nodes.push(BvhNode {
            bounds: prim_bounds.clone(),
            left: 0,
            right: 0,
            first_prim: start as u32,
            prim_count: count as u32,
        });

        if count <= MAX_LEAF_PRIMS {
            return node_idx;
        }

        let centroid_bounds = compute_centroid_bounds(prims, indices, start, end);
        let axis = centroid_bounds.longest_axis();

        let total_sa = prim_bounds.surface_area();
        let leaf_cost = count as f32;

        let (best_cost, best_split_idx) =
            find_best_sah_split(prims, indices, start, end, axis, total_sa);

        if best_cost >= leaf_cost || best_split_idx == start || best_split_idx == end {
            return node_idx;
        }

        let mid = best_split_idx;
        nodes[node_idx].prim_count = 0;

        let left_idx = build_recursive(prims, indices, nodes, start, mid);
        let right_idx = build_recursive(prims, indices, nodes, mid, end);

        nodes[node_idx].left = left_idx as u32;
        nodes[node_idx].right = right_idx as u32;

        node_idx
    }

    fn find_best_sah_split(
        prims: &[BvhPrimitive],
        indices: &mut Vec<u32>,
        start: usize,
        end: usize,
        axis: usize,
        total_sa: f32,
    ) -> (f32, usize) {
        let centroid_bounds = compute_centroid_bounds(prims, indices, start, end);
        let axis_min = centroid_bounds.min[axis];
        let axis_max = centroid_bounds.max[axis];

        if (axis_max - axis_min).abs() < f32::EPSILON {
            return (f32::INFINITY, start);
        }

        let inv_extent = 1.0 / (axis_max - axis_min);

        let mut bucket_bounds = [const { AABB { min: [f32::INFINITY; 3], max: [f32::NEG_INFINITY; 3] } }; NUM_BUCKETS];
        let mut bucket_count = [0usize; NUM_BUCKETS];

        for i in start..end {
            let pi = indices[i] as usize;
            let c = prims[pi].centroid[axis];
            let b = ((c - axis_min) * inv_extent * NUM_BUCKETS as f32) as usize;
            let b = b.min(NUM_BUCKETS - 1);
            bucket_count[b] += 1;
            bucket_bounds[b] = bucket_bounds[b].union(&prims[pi].bounds);
        }

        let mut best_cost = f32::INFINITY;
        let mut best_bucket = 0;

        for split in 1..NUM_BUCKETS {
            let mut left_bounds = AABB::empty();
            let mut right_bounds = AABB::empty();
            let mut left_count = 0usize;
            let mut right_count = 0usize;

            for b in 0..split {
                if bucket_count[b] > 0 {
                    left_bounds = left_bounds.union(&bucket_bounds[b]);
                }
                left_count += bucket_count[b];
            }
            for b in split..NUM_BUCKETS {
                if bucket_count[b] > 0 {
                    right_bounds = right_bounds.union(&bucket_bounds[b]);
                }
                right_count += bucket_count[b];
            }

            let cost = if total_sa > 0.0 {
                C_TRAV
                    + (left_count as f32 * left_bounds.surface_area()
                        + right_count as f32 * right_bounds.surface_area())
                        / total_sa
            } else {
                f32::INFINITY
            };

            if cost < best_cost {
                best_cost = cost;
                best_bucket = split;
            }
        }

        let split_pos = axis_min + best_bucket as f32 / NUM_BUCKETS as f32 * (axis_max - axis_min);

        let mid = partition(prims, indices, start, end, axis, split_pos);

        (best_cost, mid)
    }

    fn partition(
        prims: &[BvhPrimitive],
        indices: &mut Vec<u32>,
        start: usize,
        end: usize,
        axis: usize,
        split_pos: f32,
    ) -> usize {
        let mut lo = start;
        let mut hi = end;
        while lo < hi {
            if prims[indices[lo] as usize].centroid[axis] < split_pos {
                lo += 1;
            } else {
                hi -= 1;
                indices.swap(lo, hi);
            }
        }
        if lo == start || lo == end { (start + end) / 2 } else { lo }
    }

    fn compute_prim_bounds(
        prims: &[BvhPrimitive],
        indices: &[u32],
        start: usize,
        end: usize,
    ) -> AABB {
        let mut b = AABB::empty();
        for i in start..end {
            b = b.union(&prims[indices[i] as usize].bounds);
        }
        b
    }

    fn compute_centroid_bounds(
        prims: &[BvhPrimitive],
        indices: &[u32],
        start: usize,
        end: usize,
    ) -> AABB {
        let mut b = AABB::empty();
        for i in start..end {
            b = b.expand(prims[indices[i] as usize].centroid);
        }
        b
    }
}
