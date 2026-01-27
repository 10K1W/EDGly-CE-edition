# Drag-and-Drop Modeling Canvas Implementation Plan

## Overview
Create an interactive drag-and-drop canvas where users can model EDGY elements visually. Elements are represented by their SVG images, can be named, and relationships are automatically connected based on element types.

## Requirements Summary
1. **Drag-and-drop interface** - Elements can be dragged from a palette onto canvas
2. **SVG element visualization** - Use existing SVG images for each element type
3. **Editable element names** - Text input overlay on SVG for naming instances
4. **Automatic relationship connections** - Lines connect elements based on domainmodelrelationship rules
5. **Save functionality** - Save both the canvas layout and element instances
6. **New database table** - Store canvas models and element instances

---

## Architecture Overview

### Frontend Components
1. **Element Palette** - Sidebar showing all available element types with SVG icons
2. **Canvas Area** - Interactive drawing surface using SVG or HTML5 Canvas
3. **Element Instance** - Draggable SVG element with embedded text input
4. **Connection Lines** - SVG paths connecting related elements
5. **Toolbar** - Save, Load, Clear, Zoom controls

### Backend Components
1. **New Database Tables**:
   - `canvas_models` - Stores canvas configurations
   - `canvas_element_instances` - Stores element instances on canvas
   - `canvas_relationships` - Stores visual relationships (references instances)

2. **API Endpoints**:
   - `POST /api/canvas/models` - Save canvas model
   - `GET /api/canvas/models` - Load canvas models
   - `GET /api/canvas/models/:id` - Get specific model
   - `DELETE /api/canvas/models/:id` - Delete model

---

## Database Schema

### Table: `canvas_models`
```sql
CREATE TABLE IF NOT EXISTS canvas_models (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    canvas_width INTEGER DEFAULT 2000,
    canvas_height INTEGER DEFAULT 2000,
    zoom_level REAL DEFAULT 1.0,
    pan_x REAL DEFAULT 0,
    pan_y REAL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Table: `canvas_element_instances`
```sql
CREATE TABLE IF NOT EXISTS canvas_element_instances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canvas_model_id INTEGER NOT NULL,
    element_type_id INTEGER NOT NULL,  -- References domainmodel.id (the element type)
    instance_name TEXT NOT NULL,       -- User-defined name for this instance
    x_position REAL NOT NULL,          -- Canvas X coordinate
    y_position REAL NOT NULL,          -- Canvas Y coordinate
    width INTEGER DEFAULT 120,          -- Display width
    height INTEGER DEFAULT 120,         -- Display height
    z_index INTEGER DEFAULT 0,          -- Layer order
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (canvas_model_id) REFERENCES canvas_models(id) ON DELETE CASCADE,
    FOREIGN KEY (element_type_id) REFERENCES domainmodel(id)
);
```

### Table: `canvas_relationships`
```sql
CREATE TABLE IF NOT EXISTS canvas_relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canvas_model_id INTEGER NOT NULL,
    source_instance_id INTEGER NOT NULL,  -- References canvas_element_instances.id
    target_instance_id INTEGER NOT NULL, -- References canvas_element_instances.id
    relationship_type TEXT,               -- From domainmodelrelationship.relationship_type
    line_path TEXT,                       -- SVG path data for custom routing
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (canvas_model_id) REFERENCES canvas_models(id) ON DELETE CASCADE,
    FOREIGN KEY (source_instance_id) REFERENCES canvas_element_instances(id) ON DELETE CASCADE,
    FOREIGN KEY (target_instance_id) REFERENCES canvas_element_instances(id) ON DELETE CASCADE
);
```

---

## Technology Stack Recommendations

### Option 1: SVG-based (Recommended)
- **Pros**: Vector graphics, scalable, easy to manipulate, good browser support
- **Libraries**: 
  - **SVG.js** or **Snap.svg** for SVG manipulation
  - **D3.js** for force-directed layouts (optional)
  - **jsPlumb** or **Rete.js** for connection lines

### Option 2: HTML5 Canvas
- **Pros**: Better performance for many elements
- **Cons**: More complex, harder to implement text editing
- **Libraries**: **Fabric.js** or **Konva.js**

### Option 3: Hybrid Approach (Best)
- **SVG for elements** - Easy text editing, vector graphics
- **SVG for connections** - Clean lines, easy routing
- **HTML overlay for inputs** - Native text editing

---

## Implementation Plan

### Phase 1: Database Setup
1. Create new database tables (`canvas_models`, `canvas_element_instances`, `canvas_relationships`)
2. Add API endpoints for CRUD operations
3. Test database operations

### Phase 2: Basic Canvas UI
1. Create canvas container with fixed dimensions
2. Implement pan and zoom functionality
3. Add toolbar with basic controls
4. Style canvas area

### Phase 3: Element Palette
1. Create sidebar with element types
2. Display SVG icons for each element type
3. Implement drag functionality
4. Show element type names

### Phase 4: Element Instance Creation
1. Implement drop handler on canvas
2. Create element instance component:
   - SVG image from element type
   - Text input overlay (centered)
   - Position tracking
   - Drag functionality
3. Store position in component state
4. Generate unique instance ID

### Phase 5: Text Editing
1. Implement inline text editing:
   - Click to edit mode
   - Text input overlay on SVG
   - Save on blur/Enter
   - Cancel on Escape
2. Update instance name in real-time
3. Validate name (non-empty, unique within canvas)

### Phase 6: Relationship Auto-Connection
1. Load relationship rules from `domainmodelrelationship`
2. When element instance created:
   - Check element type
   - Find all relationships where this type is source or target
   - Check for existing instances of related types
   - Auto-create connection lines
3. Implement connection line rendering:
   - SVG path between elements
   - Arrow markers for direction
   - Update on element move
   - Smart routing (avoid overlaps)

### Phase 7: Manual Relationship Creation
1. Allow users to manually connect elements:
   - Click source element
   - Click target element
   - Show relationship type selector
   - Create connection
2. Validate relationship type matches element types

### Phase 8: Save/Load Functionality
1. Save canvas state:
   - Canvas dimensions and zoom
   - All element instances (positions, names)
   - All relationships
2. Load canvas state:
   - Restore element instances
   - Restore relationships
   - Restore canvas view
3. List saved models
4. Delete models

### Phase 9: Advanced Features
1. Element selection and multi-select
2. Delete elements (with cascade to relationships)
3. Copy/paste elements
4. Undo/redo functionality
5. Export as image (PNG/SVG)
6. Grid snapping
7. Alignment guides

---

## Detailed Component Design

### Element Instance Component Structure
```javascript
<div class="element-instance" data-instance-id="{id}" style="position: absolute; left: {x}px; top: {y}px;">
    <svg width="120" height="120" class="element-svg">
        <!-- SVG image from /images/Shape-{Element}.svg -->
        <image href="/images/Shape-{Element}.svg" width="120" height="120"/>
    </svg>
    <div class="element-name-overlay">
        <input type="text" 
               class="element-name-input" 
               value="{instance_name}"
               placeholder="Enter name..."
               style="position: absolute; 
                      top: 50%; 
                      left: 50%; 
                      transform: translate(-50%, -50%);
                      background: rgba(255,255,255,0.9);
                      border: 1px solid #ccc;
                      padding: 4px 8px;
                      border-radius: 4px;
                      text-align: center;
                      font-size: 12px;
                      width: 80px;"/>
    </div>
</div>
```

### Connection Line Component
```javascript
<svg class="connections-layer" style="position: absolute; top: 0; left: 0; pointer-events: none;">
    <defs>
        <marker id="arrowhead" markerWidth="10" markerHeight="10" refX="9" refY="3" orient="auto">
            <polygon points="0 0, 10 3, 0 6" fill="#666"/>
        </marker>
    </defs>
    <path d="M {x1} {y1} L {x2} {y2}" 
          stroke="#666" 
          stroke-width="2" 
          fill="none"
          marker-end="url(#arrowhead)"/>
</svg>
```

---

## API Endpoint Specifications

### POST /api/canvas/models
**Request Body:**
```json
{
    "name": "My Model",
    "description": "Description",
    "canvas_width": 2000,
    "canvas_height": 2000,
    "zoom_level": 1.0,
    "pan_x": 0,
    "pan_y": 0,
    "elements": [
        {
            "element_type_id": 1,
            "instance_name": "Customer Service",
            "x_position": 100,
            "y_position": 200,
            "width": 120,
            "height": 120
        }
    ],
    "relationships": [
        {
            "source_instance_id": 1,
            "target_instance_id": 2,
            "relationship_type": "performs"
        }
    ]
}
```

**Response:**
```json
{
    "id": 1,
    "name": "My Model",
    "message": "Canvas model saved successfully"
}
```

### GET /api/canvas/models/:id
**Response:**
```json
{
    "id": 1,
    "name": "My Model",
    "description": "Description",
    "canvas_width": 2000,
    "canvas_height": 2000,
    "zoom_level": 1.0,
    "pan_x": 0,
    "pan_y": 0,
    "elements": [
        {
            "id": 1,
            "element_type_id": 1,
            "element_type_name": "People",
            "element_type_image": "/images/Shape-People.svg",
            "instance_name": "Customer Service",
            "x_position": 100,
            "y_position": 200,
            "width": 120,
            "height": 120
        }
    ],
    "relationships": [
        {
            "id": 1,
            "source_instance_id": 1,
            "target_instance_id": 2,
            "relationship_type": "performs",
            "source_name": "Customer Service",
            "target_name": "Support Process"
        }
    ]
}
```

---

## Relationship Auto-Connection Logic

### Algorithm:
1. When element instance created with element_type_id = X:
   ```javascript
   // Find all relationships where X is source
   const sourceRelationships = relationships.filter(r => 
       r.source_element_type === elementType
   );
   
   // Find all relationships where X is target
   const targetRelationships = relationships.filter(r => 
       r.target_element_type === elementType
   );
   
   // For each relationship, check if matching instance exists
   sourceRelationships.forEach(rel => {
       const matchingInstances = existingInstances.filter(inst => 
           inst.element_type_id === rel.target_element_id
       );
       matchingInstances.forEach(target => {
           createConnection(newInstance, target, rel.relationship_type);
       });
   });
   
   targetRelationships.forEach(rel => {
       const matchingInstances = existingInstances.filter(inst => 
           inst.element_type_id === rel.source_element_id
       );
       matchingInstances.forEach(source => {
           createConnection(source, newInstance, rel.relationship_type);
       });
   });
   ```

---

## UI/UX Design Considerations

### Element Palette
- **Location**: Left sidebar (collapsible)
- **Layout**: Grid of element type cards
- **Each card shows**:
  - SVG icon (64x64px)
  - Element type name
  - Count of existing instances (optional)
- **Drag handle**: Entire card is draggable

### Canvas Area
- **Background**: Grid pattern or solid color
- **Zoom controls**: Mouse wheel + buttons
- **Pan**: Click and drag empty space
- **Selection**: Click element to select (highlight border)
- **Multi-select**: Ctrl+Click or drag selection box

### Element Instance
- **Visual feedback**:
  - Hover: Slight scale/glow
  - Selected: Blue border
  - Dragging: Semi-transparent
- **Text editing**:
  - Click name to edit
  - Auto-resize input to fit text
  - Save on blur or Enter
  - Cancel on Escape

### Connection Lines
- **Style**: 
  - Default: Gray, 2px
  - Hover: Blue, 3px
  - Selected: Blue, 3px with highlight
- **Routing**: 
  - Straight lines for simple cases
  - Curved/angled for complex layouts
  - Avoid overlapping elements
- **Labels**: Show relationship type on hover

---

## Implementation Steps (Detailed)

### Step 1: Database Schema (server.py)
- Add table creation in `init_database()`
- Test table creation

### Step 2: API Endpoints (server.py)
- Implement POST /api/canvas/models
- Implement GET /api/canvas/models
- Implement GET /api/canvas/models/:id
- Implement PUT /api/canvas/models/:id
- Implement DELETE /api/canvas/models/:id

### Step 3: Canvas HTML Structure (index.html)
- Add new section: `<div id="modelingCanvas" class="section">`
- Create canvas container
- Create element palette sidebar
- Add toolbar

### Step 4: Canvas JavaScript Setup
- Initialize canvas dimensions
- Set up pan/zoom handlers
- Create connection layer SVG
- Create element layer container

### Step 5: Element Palette
- Load element types from `/api/records`
- Render element cards with SVG images
- Implement HTML5 drag API
- Add drag preview

### Step 6: Drop Handler
- Listen for drop events on canvas
- Calculate drop position
- Create element instance component
- Add to canvas

### Step 7: Element Instance Component
- Create reusable component function
- Implement drag functionality
- Add text input overlay
- Handle name editing

### Step 8: Relationship Auto-Connection
- Load relationship rules on canvas init
- On element create, check for auto-connections
- Create connection lines
- Update on element move

### Step 9: Connection Line Rendering
- Calculate line paths
- Draw SVG paths
- Add arrow markers
- Handle updates on element move

### Step 10: Save Functionality
- Collect all element instances
- Collect all relationships
- Send to API
- Show success message

### Step 11: Load Functionality
- Fetch model from API
- Recreate element instances
- Recreate relationships
- Restore canvas view

---

## Libraries to Consider

### Core Libraries
1. **SVG.js** (https://svgjs.dev/) - SVG manipulation
   - Lightweight, easy API
   - Good for element manipulation

2. **jsPlumb** (https://jsplumbtoolkit.com/) - Connection lines
   - Excellent for node-based connections
   - Handles routing automatically
   - Free community edition available

3. **D3.js** (https://d3js.org/) - Data visualization (optional)
   - Force-directed layouts
   - Advanced path calculations
   - Larger library, use if needed

### Alternative: Lightweight Custom Solution
- Use native SVG + JavaScript
- Custom connection routing algorithm
- More control, less dependencies

---

## File Structure

```
EDGY_RepoModeller/
├── server.py (add canvas endpoints)
├── index.html (add canvas UI)
├── public/
│   ├── images/ (existing SVG files)
│   └── js/
│       └── canvas.js (new - canvas logic)
└── DRAG_DROP_CANVAS_PLAN.md (this file)
```

---

## Testing Checklist

- [ ] Elements can be dragged from palette
- [ ] Elements appear on canvas with correct SVG
- [ ] Element names can be edited
- [ ] Elements can be moved on canvas
- [ ] Relationships auto-connect correctly
- [ ] Connection lines update on element move
- [ ] Canvas can be saved
- [ ] Canvas can be loaded
- [ ] Multiple models can be saved
- [ ] Models can be deleted
- [ ] Pan and zoom work correctly
- [ ] Elements persist after page refresh

---

## Future Enhancements

1. **Templates**: Pre-built model templates
2. **Export**: Export as PlantUML, PNG, SVG
3. **Collaboration**: Real-time multi-user editing
4. **Validation**: Visual validation of EDGY rules
5. **Layouts**: Auto-layout algorithms (force-directed, hierarchical)
6. **Groups**: Group related elements
7. **Notes**: Add text notes to canvas
8. **Themes**: Different visual themes
9. **Minimap**: Overview of large canvases
10. **Search**: Find elements by name

---

## Estimated Implementation Time

- **Phase 1-2** (Database + Basic UI): 2-3 hours
- **Phase 3-4** (Palette + Drop): 3-4 hours
- **Phase 5** (Text Editing): 2-3 hours
- **Phase 6-7** (Relationships): 4-5 hours
- **Phase 8** (Save/Load): 2-3 hours
- **Phase 9** (Advanced): 4-6 hours

**Total**: ~20-25 hours for full implementation

---

## Recommended Starting Point

1. Start with **SVG.js** for element manipulation
2. Use **native SVG** for connection lines (simpler than jsPlumb initially)
3. Implement basic drag-drop first
4. Add text editing second
5. Add relationships third
6. Add save/load last

This approach allows incremental development and testing at each stage.

