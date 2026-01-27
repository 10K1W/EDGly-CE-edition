# Palette Enhancement Plan: Existing Element Instances

## Overview
Enhance the Element Palette in the Modeling Canvas to allow users to:
1. Right-click on palette element types to see existing instances of that element type
2. Drag existing element instances from the palette onto the canvas

## Summary
This enhancement adds a context menu to palette element cards that displays all existing instances of that element type currently on the canvas. Users can then drag these existing instances onto the canvas to create copies, preserving all properties and styling. This enables quick reuse of configured elements without having to manually recreate them.

### Key Features
- **Context Menu**: Right-click any palette element card to see existing instances
- **Instance List**: Shows all instances with names, icons, and count badge
- **Drag & Drop**: Drag instances from menu to canvas to create copies
- **Property Preservation**: Copied instances retain all properties and styling
- **Smart Positioning**: New instances snap to grid and avoid overlaps

## Current Implementation Analysis

### Current Palette Structure
- **Location**: `#elementPalette` sidebar (180px wide)
- **Container**: `#elementPaletteList` (grid layout, 2 columns)
- **Function**: `loadElementTypes()` creates draggable cards for each element type
- **Drag Data**: Sets `elementTypeId`, `elementType`, `elementImage` on dragstart
- **Drop Handler**: `handleDrop()` in `setupCanvasEventListeners()` creates new instances

### Current Element Instance Storage
- **State**: `canvasState.elements[]` array
- **Properties**: `id`, `element_type_id`, `element_type`, `instance_name`, `x_position`, `y_position`, `width`, `height`, `image_url`, `properties[]`

## Enhancement Requirements

### 1. Context Menu for Palette Elements

#### 1.1 UI Components
- **Context Menu Container**: Add to `#elementPalette` or create floating menu
- **Menu Structure**:
  ```
  [Element Type Name]
  └─ Show Existing Instances ▶
     └─ [Instance 1 Name]
     └─ [Instance 2 Name]
     └─ [Instance 3 Name]
     └─ ... (if more than 5, show "Show All" option)
  ```

#### 1.2 Functionality
- **Trigger**: Right-click on palette element card
- **Action**: 
  - Query `canvasState.elements[]` for instances matching `element_type_id`
  - Display list of existing instances with their `instance_name`
  - Show instance count badge if > 0
  - If no instances exist, show "No instances yet" message

#### 1.3 Implementation Details
- **Menu Positioning**: 
  - Position relative to palette card
  - Ensure visibility within palette bounds
  - Handle overflow with scrolling
- **Menu Styling**:
  - Match existing context menu styles
  - Dark theme compatible
  - Hover effects for instance items
- **Menu Behavior**:
  - Close on click outside
  - Close on instance selection
  - Support keyboard navigation (optional)

### 2. Drag Existing Instances from Palette

#### 2.1 Instance Display in Menu
- **Visual Representation**:
  - Show instance name (truncated if long)
  - Show element type icon (small version)
  - Show instance ID or creation indicator
  - Optional: Show position info (x, y)

#### 2.2 Drag Functionality
- **Make Instances Draggable**:
  - Set `draggable="true"` on instance menu items
  - Add dragstart handler
  - Set drag data:
    - `instanceId`: Existing instance ID
    - `isExistingInstance`: "true" flag
    - `elementTypeId`: Original element type ID
    - `elementType`: Element type name
    - `instanceName`: Instance name
    - `imageUrl`: Element image URL
    - `x_position`, `y_position`: Original position (for reference)
    - `width`, `height`: Original dimensions

#### 2.3 Drop Handling
- **Modify `handleDrop()` function**:
  - Check for `isExistingInstance` flag in drag data
  - If existing instance:
    - Create a COPY of the instance (new ID, new position)
    - Preserve all properties (instance_name, properties array, etc.)
    - Use same element_type_id and element_type
    - Apply new position based on drop location
    - Snap to grid
  - If new element type:
    - Use existing logic (create new instance)

#### 2.4 Copy vs Reference Decision
- **Recommendation**: Create a COPY (new instance with same data)
  - Allows multiple instances of same element with same name
  - Independent positioning and properties
  - Easier to manage (no shared state issues)
  - User can rename after dropping if needed

## Implementation Steps

### Phase 1: Context Menu Infrastructure

#### 1.1 Add HTML Structure
Add to `index.html` in the `#elementPalette` section (after `#elementPaletteList`):
```html
<!-- Palette Instance Context Menu -->
<div id="paletteInstanceMenu" style="display: none; position: fixed; z-index: 10050; 
     background: #2d2d44; border: 1px solid rgba(255,255,255,0.2); 
     border-radius: 6px; box-shadow: 0 4px 12px rgba(0,0,0,0.4); 
     min-width: 200px; max-width: 300px; max-height: 400px; overflow: hidden;">
    <div style="padding: 8px 12px; font-weight: 600; color: #ffffff; 
         border-bottom: 1px solid rgba(255,255,255,0.1); font-size: 12px;">
        <span id="paletteMenuElementType">Existing Instances</span>
        <span id="paletteMenuInstanceCount" style="float: right; color: #888; font-size: 10px;"></span>
    </div>
    <div id="paletteInstanceList" style="max-height: 320px; overflow-y: auto;">
        <!-- Instance items will be populated here -->
    </div>
    <div id="paletteInstanceEmpty" style="display: none; padding: 16px; 
         color: #888; font-size: 11px; text-align: center;">
        No instances of this element type yet
    </div>
</div>
```

#### 1.2 Add Context Menu Event Listener
Modify `loadElementTypes()` function to add contextmenu listener to each card:
```javascript
// Add context menu for showing existing instances
card.addEventListener('contextmenu', (e) => {
    e.preventDefault();
    e.stopPropagation();
    showPaletteInstanceMenu(type.id, type.name, e);
});
```

#### 1.3 Implement Menu Show/Hide Logic
```javascript
let paletteMenuRef = null;

function closePaletteInstanceMenu() {
    const menu = document.getElementById('paletteInstanceMenu');
    if (menu) {
        menu.style.display = 'none';
    }
    if (paletteMenuRef && paletteMenuRef.closeHandler) {
        document.removeEventListener('click', paletteMenuRef.closeHandler);
        paletteMenuRef = null;
    }
}

function showPaletteInstanceMenu(elementTypeId, elementTypeName, event) {
    // Close any existing menu first
    closePaletteInstanceMenu();
    
    const menu = document.getElementById('paletteInstanceMenu');
    const listContainer = document.getElementById('paletteInstanceList');
    const emptyState = document.getElementById('paletteInstanceEmpty');
    const typeLabel = document.getElementById('paletteMenuElementType');
    const countLabel = document.getElementById('paletteMenuInstanceCount');
    
    if (!menu) return;
    
    // Get instances for this element type
    const instances = getInstancesForElementType(elementTypeId);
    
    // Update header
    typeLabel.textContent = elementTypeName;
    countLabel.textContent = instances.length > 0 ? `(${instances.length})` : '';
    
    // Clear previous items
    listContainer.innerHTML = '';
    
    if (instances.length === 0) {
        // Show empty state
        emptyState.style.display = 'block';
        listContainer.style.display = 'none';
    } else {
        // Hide empty state
        emptyState.style.display = 'none';
        listContainer.style.display = 'block';
        
        // Create menu items for each instance
        instances.forEach(instance => {
            const item = createPaletteInstanceMenuItem(instance, elementTypeId);
            listContainer.appendChild(item);
        });
    }
    
    // Position menu
    const rect = event.target.getBoundingClientRect();
    const paletteRect = document.getElementById('elementPalette').getBoundingClientRect();
    let menuX = rect.right + 5;
    let menuY = rect.top;
    
    // Adjust if menu would overflow right edge
    if (menuX + 300 > window.innerWidth) {
        menuX = rect.left - 305; // Position to the left instead
    }
    
    // Adjust if menu would overflow bottom edge
    if (menuY + 400 > window.innerHeight) {
        menuY = window.innerHeight - 405;
    }
    
    menu.style.left = menuX + 'px';
    menu.style.top = menuY + 'px';
    menu.style.display = 'block';
    
    // Add click-outside handler
    const closeHandler = (e) => {
        if (!menu.contains(e.target) && !event.target.contains(e.target)) {
            closePaletteInstanceMenu();
        }
    };
    
    // Delay to avoid immediate close
    setTimeout(() => {
        document.addEventListener('click', closeHandler);
        paletteMenuRef = { closeHandler };
    }, 100);
}
```

### Phase 2: Instance Listing

#### 2.1 Create Helper Function
```javascript
function getInstancesForElementType(elementTypeId) {
    return canvasState.elements.filter(e => e.element_type_id === elementTypeId);
}
```

#### 2.2 Create Menu Item Function
```javascript
function createPaletteInstanceMenuItem(instance, elementTypeId) {
    const item = document.createElement('div');
    item.draggable = true;
    item.dataset.instanceId = instance.id;
    item.style.cssText = `
        padding: 8px 12px;
        cursor: grab;
        color: #ffffff;
        font-size: 11px;
        border-bottom: 1px solid rgba(255,255,255,0.05);
        display: flex;
        align-items: center;
        gap: 8px;
        transition: background 0.2s;
    `;
    
    // Truncate long names
    const displayName = instance.instance_name || `Instance ${instance.id}`;
    const truncatedName = displayName.length > 25 
        ? displayName.substring(0, 22) + '...' 
        : displayName;
    
    item.innerHTML = `
        <img src="${instance.image_url || `/images/Shape-${instance.element_type}.svg`}" 
             style="width: 20px; height: 20px; object-fit: contain; flex-shrink: 0;"
             onerror="this.src='/images/Shape-${instance.element_type}.svg'; this.onerror=null;">
        <span style="flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" 
              title="${displayName}">${truncatedName}</span>
    `;
    
    // Hover effects
    item.addEventListener('mouseenter', () => {
        item.style.background = '#3d3d5c';
    });
    item.addEventListener('mouseleave', () => {
        item.style.background = 'transparent';
    });
    
    // Drag start handler
    item.addEventListener('dragstart', (e) => {
        console.log('Dragging existing instance:', instance);
        e.dataTransfer.effectAllowed = 'copy';
        e.dataTransfer.setData('instanceId', instance.id.toString());
        e.dataTransfer.setData('isExistingInstance', 'true');
        e.dataTransfer.setData('elementTypeId', instance.element_type_id.toString());
        e.dataTransfer.setData('elementType', instance.element_type || '');
        e.dataTransfer.setData('instanceName', instance.instance_name || '');
        e.dataTransfer.setData('imageUrl', instance.image_url || '');
        e.dataTransfer.setData('width', instance.width.toString());
        e.dataTransfer.setData('height', instance.height.toString());
        
        // Store properties as JSON
        if (instance.properties && instance.properties.length > 0) {
            e.dataTransfer.setData('properties', JSON.stringify(instance.properties));
        }
        
        item.style.opacity = '0.5';
        closePaletteInstanceMenu(); // Close menu when dragging starts
    });
    
    item.addEventListener('dragend', () => {
        item.style.opacity = '1';
    });
    
    return item;
}
```

### Phase 3: Drag Existing Instances

#### 3.1 Update `handleDrop()` Function
Modify the `handleDrop()` function in `setupCanvasEventListeners()`:

```javascript
const handleDrop = (e) => {
    // ... existing code for preventing duplicates ...
    
    // Check types first
    const types = Array.from(e.dataTransfer.types || []);
    const hasPropertyId = types.includes('propertyId');
    const hasElementTypeId = types.includes('elementTypeId');
    const hasInstanceId = types.includes('instanceId');
    const isExistingInstance = e.dataTransfer.getData('isExistingInstance') === 'true';
    
    // ... existing property drop handling ...
    
    // Handle existing instance drop
    if (isExistingInstance && hasInstanceId) {
        console.log('Existing instance drop detected');
        
        e.preventDefault();
        e.stopPropagation();
        e.stopImmediatePropagation();
        
        window.canvasDropHandled = true;
        
        // Get instance data
        const instanceId = parseInt(e.dataTransfer.getData('instanceId'));
        const elementTypeId = parseInt(e.dataTransfer.getData('elementTypeId'));
        const elementType = e.dataTransfer.getData('elementType');
        const instanceName = e.dataTransfer.getData('instanceName');
        const imageUrl = e.dataTransfer.getData('imageUrl');
        const width = parseInt(e.dataTransfer.getData('width')) || 120;
        const height = parseInt(e.dataTransfer.getData('height')) || 120;
        
        // Get properties if available
        let properties = [];
        try {
            const propertiesJson = e.dataTransfer.getData('properties');
            if (propertiesJson) {
                properties = JSON.parse(propertiesJson);
            }
        } catch (err) {
            console.error('Error parsing properties:', err);
        }
        
        // Get original instance to copy all data
        const sourceInstance = canvasState.elements.find(e => e.id === instanceId);
        if (!sourceInstance) {
            console.error('Source instance not found:', instanceId);
            window.canvasDropHandled = false;
            return;
        }
        
        // Calculate drop position
        const rect = container.getBoundingClientRect();
        const x = (e.clientX - rect.left - canvasState.panX) / canvasState.zoom;
        const y = (e.clientY - rect.top - canvasState.panY) / canvasState.zoom;
        
        // Create copy of instance
        createInstanceCopy(sourceInstance, x, y);
        
        // Reset flag
        setTimeout(() => { 
            window.canvasDropHandled = false;
        }, 1000);
        
        return;
    }
    
    // ... existing new element drop handling ...
};
```

#### 3.2 Create Instance Copy Function
```javascript
function createInstanceCopy(sourceInstance, x, y) {
    saveStateForUndo(); // Save state before creating
    
    // Generate new ID
    const newId = canvasState.nextElementId++;
    
    // Snap to grid
    const isPeople = sourceInstance.element_type && 
                     sourceInstance.element_type.toLowerCase() === 'people';
    const elementWidth = isPeople ? 60 : (sourceInstance.width || 120);
    const elementHeight = isPeople ? 60 : (sourceInstance.height || 120);
    
    const snappedPos = snapElementToGrid(x, y, elementWidth, elementHeight);
    
    // Create copy with all properties
    const copy = {
        id: newId,
        element_type_id: sourceInstance.element_type_id,
        element_type: sourceInstance.element_type,
        instance_name: sourceInstance.instance_name, // Same name - user can rename later
        x_position: snappedPos.x,
        y_position: snappedPos.y,
        width: elementWidth,
        height: elementHeight,
        image_url: sourceInstance.image_url,
        properties: sourceInstance.properties ? [...sourceInstance.properties] : []
    };
    
    // Add to state
    canvasState.elements.push(copy);
    
    // Render on canvas
    renderElement(copy);
    
    // Update undo/redo
    updateUndoRedoButtons();
    
    console.log('Created instance copy:', copy);
}
```

### Phase 4: UI/UX Enhancements
1. Add visual indicator on palette cards showing instance count
2. Add hover effects on instance menu items
3. Add keyboard shortcuts (optional)
4. Add tooltips showing instance details
5. Handle edge cases:
   - Very long instance names
   - Many instances (pagination/scroll)
   - Empty canvas state

## Technical Considerations

### Data Structure
```javascript
// Instance menu item data
{
    id: instance.id,
    element_type_id: instance.element_type_id,
    element_type: instance.element_type,
    instance_name: instance.instance_name,
    image_url: instance.image_url,
    properties: instance.properties || [],
    x_position: instance.x_position,
    y_position: instance.y_position,
    width: instance.width,
    height: instance.height
}
```

### Function Signatures
```javascript
// Get instances for an element type
function getInstancesForElementType(elementTypeId) {
    return canvasState.elements.filter(e => e.element_type_id === elementTypeId);
}

// Show palette instance menu
function showPaletteInstanceMenu(elementTypeId, event) {
    // Prevent default context menu
    event.preventDefault();
    event.stopPropagation();
    
    // Get instances
    const instances = getInstancesForElementType(elementTypeId);
    
    // Build and show menu
    // ...
}

// Create copy of existing instance
function createInstanceCopy(sourceInstance, x, y) {
    const newId = canvasState.nextElementId++;
    const copy = {
        id: newId,
        element_type_id: sourceInstance.element_type_id,
        element_type: sourceInstance.element_type,
        instance_name: sourceInstance.instance_name, // Can be renamed later
        x_position: x,
        y_position: y,
        width: sourceInstance.width,
        height: sourceInstance.height,
        image_url: sourceInstance.image_url,
        properties: sourceInstance.properties ? [...sourceInstance.properties] : []
    };
    
    canvasState.elements.push(copy);
    renderElement(copy);
    saveStateForUndo();
    updateUndoRedoButtons();
}
```

### Menu HTML Structure
```html
<div id="paletteInstanceMenu" style="display: none; position: absolute; ...">
    <div style="padding: 4px 8px; font-weight: 600; border-bottom: 1px solid rgba(255,255,255,0.1);">
        Existing Instances
    </div>
    <div id="paletteInstanceList" style="max-height: 300px; overflow-y: auto;">
        <!-- Instance items will be populated here -->
    </div>
    <div id="paletteInstanceEmpty" style="display: none; padding: 8px; color: #888; font-size: 11px;">
        No instances yet
    </div>
</div>
```

## Edge Cases & Considerations

1. **No Instances**: Show "No instances yet" message
2. **Many Instances**: 
   - Limit display to 10-15 items
   - Add scrollbar
   - Optionally add search/filter
3. **Instance Name Length**: Truncate with ellipsis, show full name on hover
4. **Menu Positioning**: 
   - Ensure menu stays within palette bounds
   - Handle right-edge overflow
   - Handle bottom-edge overflow
5. **Menu Closing**: 
   - Click outside
   - ESC key
   - Instance selection
   - New context menu opened
6. **Performance**: 
   - Cache instance lists if needed
   - Debounce menu updates
   - Virtual scrolling for large lists (if > 50 instances)

## Testing Checklist

- [ ] Context menu appears on right-click of palette element
- [ ] Menu shows correct instances for element type
- [ ] Menu handles empty state correctly
- [ ] Menu closes on click outside
- [ ] Instance items are draggable
- [ ] Dropped instances create copies correctly
- [ ] Copied instances have correct properties
- [ ] Copied instances are positioned correctly
- [ ] Undo/redo works with instance copies
- [ ] Menu works in fullscreen mode
- [ ] Menu works with many instances (scroll)
- [ ] Menu positioning handles edge cases

## Future Enhancements (Optional)

1. **Search/Filter**: Add search box in menu to filter instances
2. **Instance Preview**: Show thumbnail or preview in menu
3. **Bulk Operations**: Select multiple instances to copy
4. **Instance Templates**: Save instance configurations as templates
5. **Quick Actions**: Delete, rename, or jump to instance from menu
6. **Instance Groups**: Group instances by name pattern or properties

