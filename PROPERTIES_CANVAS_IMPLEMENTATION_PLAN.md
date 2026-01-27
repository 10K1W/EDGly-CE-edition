# Properties Canvas Implementation Plan

## Overview
Implement Properties as draggable canvas elements that can be associated with Element Instances, similar to how Element Instances work. Properties will appear in the palette, can be dropped onto Element Instances, and will be positioned and sized relative to their parent Element Instance.

## Requirements Summary
1. Properties available in Palette
2. Drag and drop Properties onto Element Instances
3. Properties positioned at bottom of Element Instance, almost same width, centered
4. Editable text box (same behavior as Element Instance)
5. Context menu with delete option

---

## Phase 1: Database Schema

### 1.1 New Table: `canvas_property_instances`
Create a new table to store property instances on the canvas, similar to `canvas_element_instances`.

```sql
CREATE TABLE IF NOT EXISTS canvas_property_instances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canvas_model_id INTEGER NOT NULL,
    property_id INTEGER NOT NULL,  -- References domainelementproperties.id (the property template)
    element_instance_id INTEGER NOT NULL,  -- References canvas_element_instances.id (parent element)
    instance_name TEXT NOT NULL,  -- User-editable name for this property instance
    x_position REAL NOT NULL,  -- Canvas X coordinate (relative to parent)
    y_position REAL NOT NULL,  -- Canvas Y coordinate (relative to parent)
    width INTEGER DEFAULT 100,  -- Display width (typically ~90% of parent width)
    height INTEGER DEFAULT 30,  -- Display height
    z_index INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (canvas_model_id) REFERENCES canvas_models(id) ON DELETE CASCADE,
    FOREIGN KEY (property_id) REFERENCES domainelementproperties(id),
    FOREIGN KEY (element_instance_id) REFERENCES canvas_element_instances(id) ON DELETE CASCADE
);
```

### 1.2 Database Migration
- Add migration function in `server.py` `init_database()` function
- Create index on `element_instance_id` for performance
- Create index on `canvas_model_id` for queries

---

## Phase 2: Backend API Endpoints

### 2.1 Get Properties for Palette
**Endpoint:** `GET /api/canvas/properties/palette`
- Returns all unique properties from `domainelementproperties` table
- Group by `propertyname` and `ragtype` to avoid duplicates
- Include: `id`, `propertyname`, `ragtype`, `image_url`, `description`
- Response format:
```json
[
  {
    "id": 1,
    "propertyname": "Security",
    "ragtype": "positive",
    "image_url": "/images/Tag-Green.svg",
    "description": "Security property"
  }
]
```

### 2.2 Create Property Instance
**Endpoint:** `POST /api/canvas/property-instances`
- Creates a new property instance on canvas
- Request body:
```json
{
  "canvas_model_id": 1,
  "property_id": 5,
  "element_instance_id": 10,
  "instance_name": "Security",
  "x_position": 100.0,
  "y_position": 250.0,
  "width": 108,
  "height": 30
}
```
- Returns created property instance with database ID

### 2.3 Update Property Instance
**Endpoint:** `PUT /api/canvas/property-instances/<int:property_instance_id>`
- Updates property instance (mainly for name editing and repositioning)
- Request body: `{ "instance_name": "...", "x_position": ..., "y_position": ... }`

### 2.4 Delete Property Instance
**Endpoint:** `DELETE /api/canvas/property-instances/<int:property_instance_id>`
- Deletes a property instance from canvas

### 2.5 Get Property Instances for Model
**Endpoint:** `GET /api/canvas/models/<int:model_id>/property-instances`
- Returns all property instances for a canvas model
- Include property template data (propertyname, ragtype, image_url)

### 2.6 Update Canvas Model Save/Load
- Modify `POST /api/canvas/models` to include property instances
- Modify `GET /api/canvas/models/<id>` to return property instances
- Modify `PUT /api/canvas/models/<id>` to save property instances

---

## Phase 3: Frontend - Canvas State

### 3.1 Extend `canvasState` Object
Add property instances to canvas state:
```javascript
canvasState = {
    // ... existing properties
    propertyInstances: [],  // Array of property instances on canvas
    nextPropertyInstanceId: 1  // Counter for temporary IDs
};
```

### 3.2 Property Instance Data Structure
```javascript
{
    id: 1,  // Temporary ID or database ID
    property_id: 5,  // Reference to property template
    element_instance_id: 10,  // Parent element instance
    instance_name: "Security",
    x_position: 100.0,
    y_position: 250.0,
    width: 108,
    height: 30,
    propertyname: "Security",  // From template
    ragtype: "positive",  // From template
    image_url: "/images/Tag-Green.svg"  // From template
}
```

---

## Phase 4: Frontend - Palette Integration

### 4.1 Add Properties Section to Palette
- Add a new section in the palette sidebar (below element types)
- Title: "Properties"
- Load properties using `GET /api/canvas/properties/palette`
- Display properties in a grid similar to element types

### 4.2 Property Palette Card
- Create draggable cards for each property
- Display: property image (RAG tag), property name
- Style similar to element palette cards
- Drag data: `propertyId`, `propertyname`, `ragtype`, `image_url`

### 4.3 Function: `loadPropertiesForPalette()`
```javascript
async function loadPropertiesForPalette() {
    try {
        const response = await fetch('/api/canvas/properties/palette');
        const properties = await response.json();
        
        const palette = document.getElementById('propertyPaletteList');
        palette.innerHTML = '';
        
        properties.forEach(prop => {
            const card = createPropertyPaletteCard(prop);
            palette.appendChild(card);
        });
    } catch (error) {
        console.error('Error loading properties:', error);
    }
}
```

---

## Phase 5: Frontend - Drag and Drop

### 5.1 Modify Canvas Drop Handler
Update `setupCanvasEventListeners()` drop handler to:
1. Detect if drop is a property (check for `propertyId` in dataTransfer)
2. If property dropped on element instance:
   - Calculate position (bottom center of element instance)
   - Create property instance
   - Associate with element instance
3. If property dropped on empty canvas: ignore (properties must be on elements)

### 5.2 Calculate Property Position
Function: `calculatePropertyPosition(elementInstance)`
```javascript
function calculatePropertyPosition(elementInstance) {
    // Position at bottom center of element instance
    const propertyWidth = Math.floor(elementInstance.width * 0.9);  // 90% of element width
    const propertyHeight = 30;
    
    return {
        x: elementInstance.x_position + (elementInstance.width - propertyWidth) / 2,  // Centered
        y: elementInstance.y_position + elementInstance.height + 5,  // Below element, 5px gap
        width: propertyWidth,
        height: propertyHeight
    };
}
```

### 5.3 Create Property Instance Function
```javascript
function createPropertyInstance(propertyId, propertyData, elementInstanceId) {
    const elementInstance = canvasState.elements.find(e => e.id === elementInstanceId);
    if (!elementInstance) return;
    
    const position = calculatePropertyPosition(elementInstance);
    
    const propertyInstance = {
        id: canvasState.nextPropertyInstanceId++,
        property_id: propertyId,
        element_instance_id: elementInstanceId,
        instance_name: propertyData.propertyname,
        x_position: position.x,
        y_position: position.y,
        width: position.width,
        height: position.height,
        propertyname: propertyData.propertyname,
        ragtype: propertyData.ragtype,
        image_url: propertyData.image_url
    };
    
    canvasState.propertyInstances.push(propertyInstance);
    renderPropertyInstance(propertyInstance);
    saveStateForUndo();
}
```

---

## Phase 6: Frontend - Rendering

### 6.1 Create Property Instance Layer
- Add new layer: `<div id="propertyInstancesLayer"></div>` in canvas container
- Position: absolute, same as elements layer
- Z-index: higher than elements layer (so properties appear on top)

### 6.2 Render Property Instance Function
```javascript
function renderPropertyInstance(propertyInstance) {
    const layer = document.getElementById('propertyInstancesLayer');
    if (!layer) return;
    
    const propertyDiv = document.createElement('div');
    propertyDiv.id = `property-${propertyInstance.id}`;
    propertyDiv.className = 'canvas-property';
    
    // Style similar to element instances but smaller
    propertyDiv.style.cssText = `
        position: absolute;
        left: ${propertyInstance.x_position}px;
        top: ${propertyInstance.y_position}px;
        width: ${propertyInstance.width}px;
        height: ${propertyInstance.height}px;
        background: #2d2d44;
        border: 1px solid rgba(255,255,255,0.2);
        border-radius: 4px;
        display: flex;
        align-items: center;
        padding: 4px 8px;
        cursor: move;
        user-select: none;
    `;
    
    // Add property image (RAG tag)
    const imageHtml = propertyInstance.image_url 
        ? `<img src="${propertyInstance.image_url}" alt="${propertyInstance.ragtype}" 
             style="width: 20px; height: 20px; margin-right: 6px; object-fit: contain;">`
        : '';
    
    // Add editable label (similar to element instances)
    propertyDiv.innerHTML = `
        ${imageHtml}
        <div id="property-label-${propertyInstance.id}" 
             class="property-name-label"
             style="flex: 1; color: #ffffff; font-size: 11px; text-align: center;">
            ${escapeHtml(propertyInstance.instance_name)}
        </div>
        <input type="text" 
               id="property-input-${propertyInstance.id}"
               class="property-name-input"
               value="${escapeHtml(propertyInstance.instance_name)}"
               style="display: none; ...">
    `;
    
    // Add event listeners for editing, dragging, context menu
    setupPropertyInstanceEvents(propertyDiv, propertyInstance);
    
    layer.appendChild(propertyDiv);
}
```

### 6.3 Update Element Instance Rendering
- When element instance is moved, update associated property positions
- When element instance is deleted, delete associated properties

---

## Phase 7: Frontend - Editing

### 7.1 Property Name Editing
- Click on property label to edit (same as element instances)
- Functions: `startEditingProperty()`, `finishEditingProperty()`, `cancelEditingProperty()`
- Save on blur or Enter key
- Cancel on Escape key
- Update `instance_name` in canvasState and database

### 7.2 Property Dragging
- Allow dragging property instances (but keep them relative to parent element)
- When dragged, update position but maintain association with element instance
- Optionally: snap property to bottom of element instance when near

---

## Phase 8: Frontend - Context Menu

### 8.1 Property Context Menu
- Right-click on property instance shows context menu
- Menu options:
  - **Delete** - Remove property instance from canvas
  - (Future: Edit Property, View Details, etc.)

### 8.2 Delete Property Function
```javascript
function deletePropertyInstance(propertyInstanceId) {
    const index = canvasState.propertyInstances.findIndex(p => p.id === propertyInstanceId);
    if (index === -1) return;
    
    const propertyInstance = canvasState.propertyInstances[index];
    
    // Remove from DOM
    const propertyDiv = document.getElementById(`property-${propertyInstanceId}`);
    if (propertyDiv) propertyDiv.remove();
    
    // Remove from state
    canvasState.propertyInstances.splice(index, 1);
    
    // Delete from database if saved
    if (propertyInstance.id > 1000) {  // Database ID (not temporary)
        fetch(`/api/canvas/property-instances/${propertyInstance.id}`, {
            method: 'DELETE'
        });
    }
    
    saveStateForUndo();
}
```

---

## Phase 9: Frontend - Save/Load

### 9.1 Save Property Instances
- Modify `saveCanvasModel()` to include property instances
- Send property instances array in save request
- Map temporary IDs to database IDs on save

### 9.2 Load Property Instances
- Modify `loadCanvasModel()` to load property instances
- Render property instances after loading model
- Maintain associations with element instances

---

## Phase 10: Positioning Logic

### 10.1 Auto-Positioning
- When property is dropped, automatically position at bottom center
- When element instance is moved, update property positions
- When element instance is resized, recalculate property width

### 10.2 Multiple Properties
- Stack properties vertically below element instance
- Each property: 5px gap between them
- Recalculate positions when properties are added/removed

### 10.3 Function: `updatePropertyPositionsForElement(elementInstanceId)`
```javascript
function updatePropertyPositionsForElement(elementInstanceId) {
    const elementInstance = canvasState.elements.find(e => e.id === elementInstanceId);
    if (!elementInstance) return;
    
    const properties = canvasState.propertyInstances.filter(
        p => p.element_instance_id === elementInstanceId
    );
    
    properties.forEach((prop, index) => {
        const position = calculatePropertyPosition(elementInstance, index);
        prop.x_position = position.x;
        prop.y_position = position.y;
        prop.width = position.width;
        
        // Update DOM
        const propDiv = document.getElementById(`property-${prop.id}`);
        if (propDiv) {
            propDiv.style.left = `${position.x}px`;
            propDiv.style.top = `${position.y}px`;
            propDiv.style.width = `${position.width}px`;
        }
    });
}
```

---

## Phase 11: Visual Design

### 11.1 Property Visual Style
- Background: `#2d2d44` (slightly darker than elements)
- Border: `1px solid rgba(255,255,255,0.2)`
- Border radius: `4px`
- Height: `30px` (fixed)
- Width: `90%` of parent element width
- Font size: `11px`
- Display RAG tag image on left (20x20px)
- Text centered

### 11.2 Hover/Selection States
- Hover: Slight background color change
- Selected: Border color change (blue)
- Editing: Show input field with border highlight

---

## Phase 12: Testing Checklist

### 12.1 Basic Functionality
- [ ] Properties appear in palette
- [ ] Properties can be dragged from palette
- [ ] Properties can be dropped on element instances
- [ ] Properties are positioned correctly (bottom center)
- [ ] Properties have correct width (90% of element)
- [ ] Properties display RAG tag image
- [ ] Properties show property name

### 12.2 Editing
- [ ] Click property name to edit
- [ ] Enter key saves changes
- [ ] Escape key cancels editing
- [ ] Blur saves changes
- [ ] Changes persist after save

### 12.3 Context Menu
- [ ] Right-click shows context menu
- [ ] Delete removes property from canvas
- [ ] Delete removes from database

### 12.4 Positioning
- [ ] Properties stay with element when element moves
- [ ] Multiple properties stack correctly
- [ ] Properties reposition when element resizes

### 12.5 Save/Load
- [ ] Property instances save with model
- [ ] Property instances load with model
- [ ] Associations maintained after load

---

## Implementation Order

1. **Phase 1**: Database schema
2. **Phase 2**: Backend API endpoints
3. **Phase 3**: Frontend canvas state
4. **Phase 4**: Palette integration
5. **Phase 5**: Drag and drop
6. **Phase 6**: Rendering
7. **Phase 7**: Editing
8. **Phase 8**: Context menu
9. **Phase 9**: Save/load
10. **Phase 10**: Positioning logic
11. **Phase 11**: Visual polish
12. **Phase 12**: Testing

---

## Notes

- Properties are instance-specific (each property instance can have different name)
- Properties maintain association with element instance (parent-child relationship)
- Properties can be manually repositioned but default to bottom center
- Properties width scales with element instance width
- Multiple properties stack vertically below element instance
- Property instances are saved/loaded with canvas models

