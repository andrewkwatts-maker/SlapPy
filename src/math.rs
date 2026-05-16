use pyo3::prelude::*;

#[pyclass]
#[derive(Clone, Copy)]
pub struct Vec2 {
    #[pyo3(get, set)]
    pub x: f32,
    #[pyo3(get, set)]
    pub y: f32,
}

#[pymethods]
impl Vec2 {
    #[new]
    pub fn new(x: f32, y: f32) -> Self {
        Self { x, y }
    }

    pub fn __add__(&self, other: Vec2) -> Vec2 {
        Vec2 { x: self.x + other.x, y: self.y + other.y }
    }

    pub fn __sub__(&self, other: Vec2) -> Vec2 {
        Vec2 { x: self.x - other.x, y: self.y - other.y }
    }

    pub fn __mul__(&self, scalar: f32) -> Vec2 {
        Vec2 { x: self.x * scalar, y: self.y * scalar }
    }

    pub fn __repr__(&self) -> String {
        format!("Vec2({}, {})", self.x, self.y)
    }

    pub fn dot(&self, other: Vec2) -> f32 {
        self.x * other.x + self.y * other.y
    }

    pub fn length(&self) -> f32 {
        (self.x * self.x + self.y * self.y).sqrt()
    }

    pub fn normalize(&self) -> Vec2 {
        let len = self.length();
        if len == 0.0 {
            Vec2 { x: 0.0, y: 0.0 }
        } else {
            Vec2 { x: self.x / len, y: self.y / len }
        }
    }

    pub fn lerp(&self, other: Vec2, t: f32) -> Vec2 {
        Vec2 {
            x: self.x + (other.x - self.x) * t,
            y: self.y + (other.y - self.y) * t,
        }
    }
}

#[pyclass]
#[derive(Clone, Copy)]
pub struct AABB {
    #[pyo3(get, set)]
    pub min_x: f32,
    #[pyo3(get, set)]
    pub min_y: f32,
    #[pyo3(get, set)]
    pub max_x: f32,
    #[pyo3(get, set)]
    pub max_y: f32,
}

#[pymethods]
impl AABB {
    #[new]
    pub fn new(min_x: f32, min_y: f32, max_x: f32, max_y: f32) -> Self {
        Self { min_x, min_y, max_x, max_y }
    }

    pub fn __repr__(&self) -> String {
        format!("AABB(({}, {}), ({}, {}))", self.min_x, self.min_y, self.max_x, self.max_y)
    }

    pub fn contains(&self, v: Vec2) -> bool {
        v.x >= self.min_x && v.x <= self.max_x && v.y >= self.min_y && v.y <= self.max_y
    }

    pub fn intersects(&self, other: AABB) -> bool {
        self.min_x <= other.max_x
            && self.max_x >= other.min_x
            && self.min_y <= other.max_y
            && self.max_y >= other.min_y
    }

    pub fn center(&self) -> Vec2 {
        Vec2 {
            x: (self.min_x + self.max_x) * 0.5,
            y: (self.min_y + self.max_y) * 0.5,
        }
    }

    pub fn size(&self) -> Vec2 {
        Vec2 {
            x: self.max_x - self.min_x,
            y: self.max_y - self.min_y,
        }
    }

    pub fn expand(&self, amount: f32) -> AABB {
        AABB {
            min_x: self.min_x - amount,
            min_y: self.min_y - amount,
            max_x: self.max_x + amount,
            max_y: self.max_y + amount,
        }
    }
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<Vec2>()?;
    m.add_class::<AABB>()?;
    Ok(())
}
