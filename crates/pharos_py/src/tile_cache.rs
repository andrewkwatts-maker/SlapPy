use pyo3::prelude::*;
use std::collections::{HashMap, VecDeque};

#[pyclass]
pub struct TileCache {
    capacity: usize,
    cache: HashMap<(i32, i32), Vec<u8>>,
    order: VecDeque<(i32, i32)>,  // front = most recently used
}

#[pymethods]
impl TileCache {
    #[new]
    pub fn new(capacity: usize) -> Self {
        TileCache {
            capacity: capacity.max(1),
            cache: HashMap::new(),
            order: VecDeque::new(),
        }
    }

    /// Insert or update a tile. Returns the evicted tile key if capacity was exceeded.
    pub fn put(&mut self, tile_x: i32, tile_y: i32, data: Vec<u8>) -> Option<(i32, i32)> {
        let key = (tile_x, tile_y);
        // Remove from order if already present (update)
        self.order.retain(|k| k != &key);
        self.cache.insert(key, data);
        self.order.push_front(key);

        if self.cache.len() > self.capacity {
            // Evict LRU (back of deque)
            if let Some(evicted) = self.order.pop_back() {
                self.cache.remove(&evicted);
                return Some(evicted);
            }
        }
        None
    }

    /// Get a tile's data (marks it as recently used).
    pub fn get(&mut self, tile_x: i32, tile_y: i32) -> Option<Vec<u8>> {
        let key = (tile_x, tile_y);
        if self.cache.contains_key(&key) {
            self.order.retain(|k| k != &key);
            self.order.push_front(key);
            self.cache.get(&key).cloned()
        } else {
            None
        }
    }

    /// Check if a tile is in cache (does not update LRU order).
    pub fn contains(&self, tile_x: i32, tile_y: i32) -> bool {
        self.cache.contains_key(&(tile_x, tile_y))
    }

    /// Remove a tile from cache.
    pub fn evict(&mut self, tile_x: i32, tile_y: i32) -> bool {
        let key = (tile_x, tile_y);
        self.order.retain(|k| k != &key);
        self.cache.remove(&key).is_some()
    }

    /// Return all tile keys currently in cache.
    pub fn keys(&self) -> Vec<(i32, i32)> {
        self.cache.keys().cloned().collect()
    }

    /// Current number of cached tiles.
    pub fn len(&self) -> usize {
        self.cache.len()
    }

    /// Maximum capacity.
    pub fn capacity(&self) -> usize {
        self.capacity
    }

    /// Clear all tiles.
    pub fn clear(&mut self) {
        self.cache.clear();
        self.order.clear();
    }
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<TileCache>()?;
    Ok(())
}
