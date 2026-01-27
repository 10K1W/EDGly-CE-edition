# Drag-and-Drop Modeling Implementation Plan

## Quick Reference: Implementation Strategy

### Core Approach
1. **Single Element Diagrams**: Generate individual PlantUML diagrams per element, store as reusable components
2. **Composite Diagrams**: Build larger diagrams by embedding element diagrams using PlantUML code concatenation (since `!includeurl` may not work with dynamic content)
3. **Layout Management**: Store element positions as JSON, convert to PlantUML positioning hints
4. **Chatbot Integration**: Extend chatbot to understand diagram manipulation commands

## Phase 1: Database Schema (Foundation)

### SQL Migration Script
```sql
-- Single element diagrams table
CREATE TABLE IF NOT EXISTS element_diagrams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    element_id INTEGER NOT NULL UNIQUE,
    plantuml_code TEXT NOT NULL,
    encoded_url TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (element_id) REFERENCES domainmodel(id)
);

-- Enhanced composite diagrams
ALTER TABLE plantumldiagrams ADD COLUMN diagram_type TEXT DEFAULT 'composite';
ALTER TABLE plantumldiagrams ADD COLUMN layout_data TEXT; -- JSON: {element_id: {x, y, width, height}}
ALTER TABLE plantumldiagrams ADD COLUMN uses_embedding BOOLEAN DEFAULT 0;

-- Composite diagram element positions
CREATE TABLE IF NOT EXISTS composite_diagram_elements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    diagram_id INTEGER NOT NULL,
    element_id INTEGER NOT NULL,
    layout_x INTEGER DEFAULT 0,
    layout_y INTEGER DEFAULT 0,
    z_index INTEGER DEFAULT 0,
    visible BOOLEAN DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (diagram_id) REFERENCES plantumldiagrams(id),
    FOREIGN KEY (element_id) REFERENCES domainmodel(id),
    UNIQUE(diagram_id, element_id)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_element_diagrams_element ON element_diagrams(element_id);
CREATE INDEX IF NOT EXISTS idx_composite_diagram_elements_diagram ON composite_diagram_elements(diagram_id);
CREATE INDEX IF NOT EXISTS idx_composite_diagram_elements_element ON composite_diagram_elements(element_id);
```

## Phase 2: Backend API Endpoints

### 2.1 Single Element Diagram Generation

```python
def generate_single_element_diagram(element_id, include_notes=False, include_properties=False):
    """Generate PlantUML code for a single element"""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        # Get element data
        cur.execute('''
            SELECT id, name, description, enterprise, facet, element
            FROM domainmodel
            WHERE id = ?
        ''', (element_id,))
        element = cur.fetchone()
        
        if not element:
            return None
        
        elem_id, name, description, enterprise, facet, element_type = element
        
        # Get element properties if needed
        element_properties = {}
        if include_properties:
            cur.execute('''
                SELECT ragtype, propertyname, description, image_url
                FROM domainelementproperties
                WHERE element_id = ?
            ''', (element_id,))
            props = cur.fetchall()
            element_properties[elem_id] = [
                {'ragtype': p[0], 'propertyname': p[1], 'description': p[2], 'image_url': p[3]}
                for p in props
            ]
        
        # Generate PlantUML code for single element
        plantuml_code = "@startuml\n"
        plantuml_code += "!include <edgy/edgy>\n\n"
        plantuml_code += "top to bottom direction\n\n"
        
        # Determine macro and variable name
        element_lower = (element_type or "").lower()
        element_name_for_link = name or element_type or "Element"
        sanitized_name = element_name_for_link.replace(" ", "_").replace("-", "_").replace("&", "And")
        sanitized_name = ''.join(c if c.isalnum() or c == '_' else '' for c in sanitized_name)
        if sanitized_name and not sanitized_name[0].isalpha():
            sanitized_name = 'E' + sanitized_name
        link_var_name = sanitized_name or "Element"
        
        # Map element type to macro
        macro_map = {
            'capability': '$capability',
            'asset': '$asset',
            'process': '$process',
            'purpose': '$purpose',
            'content': '$content',
            'story': '$story',
            'channel': '$channel',
            'journey': '$journey',
            'task': '$task',
            'product': '$product',
            'organisation': '$organisation',
            'brand': '$brand',
            'people': '$people',
            'outcome': '$outcome',
            'object': '$object'
        }
        
        macro_name = macro_map.get(element_lower, '$people')
        capitalized_name = str(name or '').capitalize()
        
        # Generate element declaration
        if macro_name in ['$product', '$organisation', '$brand']:
            var_name = element_lower if element_lower in ['product', 'organisation', 'brand'] else link_var_name.lower()
            plantuml_code += f'{macro_name}({capitalized_name}, {var_name})\n'
        else:
            plantuml_code += f'{macro_name}("{capitalized_name}")\n'
        
        # Add notes if requested
        if include_notes and description:
            desc_text = str(description).replace('"', "'").strip()
            if desc_text:
                wrapped_lines = wrap_text(desc_text, max_width=60)
                note_text = "\n        ".join(wrapped_lines)
                plantuml_code += f'    note right of {link_var_name}\n'
                plantuml_code += f'        {note_text}\n'
                plantuml_code += f'    end note\n'
        
        # Add properties if requested
        if include_properties and element_properties.get(elem_id):
            for prop in element_properties[elem_id]:
                prop_name = prop.get('propertyname', '')
                prop_desc = prop.get('description', '')
                ragtype = prop.get('ragtype', '').lower()
                
                if prop_name and prop_desc:
                    prop_text = f"{prop_name}: {prop_desc}"
                    wrapped_prop = wrap_text(prop_text, max_width=60)
                    prop_note_text = "\n        ".join(wrapped_prop)
                    
                    # Color code by RAG type
                    if ragtype == 'negative':
                        plantuml_code += f'    note right of {link_var_name} #FF5100\n'
                    elif ragtype == 'positive':
                        plantuml_code += f'    note right of {link_var_name} #20ED00\n'
                    elif ragtype == 'warning':
                        plantuml_code += f'    note right of {link_var_name} #FFE400\n'
                    else:
                        plantuml_code += f'    note right of {link_var_name}\n'
                    
                    plantuml_code += f'        {prop_note_text}\n'
                    plantuml_code += f'    end note\n'
        
        plantuml_code += "\n@enduml"
        
        # Encode
        encoded = encode_plantuml(plantuml_code)
        
        # Store in element_diagrams table
        cur.execute('''
            INSERT OR REPLACE INTO element_diagrams 
            (element_id, plantuml_code, encoded_url, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        ''', (element_id, plantuml_code, encoded))
        conn.commit()
        
        return {
            'element_id': element_id,
            'plantuml_code': plantuml_code,
            'encoded_url': encoded,
            'element': {
                'id': elem_id,
                'name': name,
                'element': element_type,
                'facet': facet,
                'enterprise': enterprise
            }
        }
    finally:
        if conn:
            conn.close()

@app.route('/api/elements/<int:element_id>/diagram', methods=['GET'])
def get_element_diagram(element_id):
    """Get or generate single element diagram"""
    include_notes = request.args.get('include_notes', 'false').lower() == 'true'
    include_properties = request.args.get('include_properties', 'false').lower() == 'true'
    regenerate = request.args.get('regenerate', 'false').lower() == 'true'
    
    conn = get_db_connection()
    try:
        if not regenerate:
            # Try to get existing diagram
            cur = conn.cursor()
            cur.execute('''
                SELECT element_id, plantuml_code, encoded_url
                FROM element_diagrams
                WHERE element_id = ?
            ''', (element_id,))
            existing = cur.fetchone()
            if existing:
                return jsonify({
                    'element_id': existing[0],
                    'plantuml_code': existing[1],
                    'encoded_url': existing[2]
                })
        
        # Generate new diagram
        result = generate_single_element_diagram(element_id, include_notes, include_properties)
        if result:
            return jsonify(result)
        else:
            return jsonify({'error': 'Element not found'}), 404
    finally:
        if conn:
            conn.close()
```

### 2.2 Composite Diagram with Embedding

```python
def generate_composite_diagram_with_embedding(diagram_id, element_ids, layout_data=None, relationships=None):
    """Generate composite diagram by embedding single element diagrams"""
    conn = get_db_connection()
    try:
        # Start composite diagram
        plantuml_code = "@startuml\n"
        plantuml_code += "!include <edgy/edgy>\n\n"
        plantuml_code += "top to bottom direction\n\n"
        
        # Get element diagrams and embed them
        element_map = {}  # element_id -> variable_name
        cur = conn.cursor()
        
        for element_id in element_ids:
            # Get element diagram code
            cur.execute('''
                SELECT plantuml_code
                FROM element_diagrams
                WHERE element_id = ?
            ''', (element_id,))
            elem_diagram = cur.fetchone()
            
            if elem_diagram:
                elem_code = elem_diagram[0]
                # Extract element declaration from element diagram
                # Remove @startuml/@enduml and includes
                clean_code = elem_code.replace('@startuml', '').replace('@enduml', '')
                clean_code = re.sub(r'!include\s+<[^>]+>\n', '', clean_code)
                clean_code = re.sub(r'top to bottom direction\n', '', clean_code)
                clean_code = clean_code.strip()
                
                # Add element code to composite
                plantuml_code += f"{clean_code}\n\n"
                
                # Extract variable name for relationships
                # Get element name from database
                cur.execute('SELECT name FROM domainmodel WHERE id = ?', (element_id,))
                elem_name = cur.fetchone()
                if elem_name:
                    name = elem_name[0] or "Element"
                    sanitized = name.replace(" ", "_").replace("-", "_")
                    sanitized = ''.join(c if c.isalnum() or c == '_' else '' for c in sanitized)
                    if sanitized and not sanitized[0].isalpha():
                        sanitized = 'E' + sanitized
                    element_map[element_id] = sanitized or "Element"
        
        # Add relationships
        if relationships:
            for rel in relationships:
                source_id = rel.get('source')
                target_id = rel.get('target')
                rel_type = rel.get('type', 'relates')
                
                source_var = element_map.get(source_id)
                target_var = element_map.get(target_id)
                
                if source_var and target_var:
                    rel_label = rel_type.replace("_", " ").title()
                    plantuml_code += f'$link({source_var}, {target_var}, "{rel_label}")\n'
        
        plantuml_code += "\n@enduml"
        
        # Encode and store
        encoded = encode_plantuml(plantuml_code)
        
        # Update diagram
        layout_json = json.dumps(layout_data) if layout_data else None
        cur.execute('''
            UPDATE plantumldiagrams
            SET plantuml_code = ?,
                encoded_url = ?,
                layout_data = ?,
                uses_embedding = 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (plantuml_code, encoded, layout_json, diagram_id))
        
        # Update composite_diagram_elements
        cur.execute('DELETE FROM composite_diagram_elements WHERE diagram_id = ?', (diagram_id,))
        for element_id in element_ids:
            layout = layout_data.get(str(element_id), {}) if layout_data else {}
            cur.execute('''
                INSERT INTO composite_diagram_elements
                (diagram_id, element_id, layout_x, layout_y, visible)
                VALUES (?, ?, ?, ?, 1)
            ''', (diagram_id, element_id, layout.get('x', 0), layout.get('y', 0)))
        
        conn.commit()
        
        return {
            'diagram_id': diagram_id,
            'plantuml_code': plantuml_code,
            'encoded_url': encoded,
            'layout_data': layout_data
        }
    finally:
        if conn:
            conn.close()

@app.route('/api/diagrams/composite', methods=['POST'])
def create_composite_diagram():
    """Create a new composite diagram"""
    data = request.json
    title = data.get('title', 'Composite Diagram')
    element_ids = data.get('element_ids', [])
    layout_data = data.get('layout_data', {})
    relationships = data.get('relationships', [])
    enterprise_filter = data.get('enterprise_filter')
    
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        # Create diagram record
        cur.execute('''
            INSERT INTO plantumldiagrams
            (title, plantuml_code, enterprise_filter, diagram_type, uses_embedding, created_at, updated_at)
            VALUES (?, ?, ?, 'composite', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ''', (title, '', enterprise_filter))
        diagram_id = cur.lastrowid
        conn.commit()
        
        # Generate composite diagram
        result = generate_composite_diagram_with_embedding(
            diagram_id, element_ids, layout_data, relationships
        )
        
        return jsonify(result), 201
    finally:
        if conn:
            conn.close()

@app.route('/api/diagrams/<int:diagram_id>/elements/<int:element_id>', methods=['POST', 'DELETE', 'PUT'])
def manage_diagram_element(diagram_id, element_id):
    """Add, remove, or update element in composite diagram"""
    conn = get_db_connection()
    try:
        if request.method == 'POST':
            # Add element
            layout_data = request.json.get('layout_data', {})
            x = layout_data.get('x', 0)
            y = layout_data.get('y', 0)
            
            cur = conn.cursor()
            cur.execute('''
                INSERT OR REPLACE INTO composite_diagram_elements
                (diagram_id, element_id, layout_x, layout_y, visible)
                VALUES (?, ?, ?, ?, 1)
            ''', (diagram_id, element_id, x, y))
            conn.commit()
            
            # Regenerate composite diagram
            cur.execute('''
                SELECT element_id FROM composite_diagram_elements
                WHERE diagram_id = ? AND visible = 1
            ''', (diagram_id,))
            element_ids = [row[0] for row in cur.fetchall()]
            
            # Get layout data
            cur.execute('''
                SELECT element_id, layout_x, layout_y
                FROM composite_diagram_elements
                WHERE diagram_id = ?
            ''', (diagram_id,))
            layout_data = {
                str(row[0]): {'x': row[1], 'y': row[2]}
                for row in cur.fetchall()
            }
            
            # Get relationships
            cur.execute('''
                SELECT r.source_element_id, r.target_element_id, r.relationship_type
                FROM domainmodelrelationship r
                WHERE r.source_element_id IN ({}) AND r.target_element_id IN ({})
            '''.format(','.join(['?']*len(element_ids)), ','.join(['?']*len(element_ids))),
            element_ids + element_ids)
            relationships = [
                {'source': r[0], 'target': r[1], 'type': r[2]}
                for r in cur.fetchall()
            ]
            
            result = generate_composite_diagram_with_embedding(
                diagram_id, element_ids, layout_data, relationships
            )
            return jsonify(result)
            
        elif request.method == 'DELETE':
            # Remove element
            cur = conn.cursor()
            cur.execute('''
                UPDATE composite_diagram_elements
                SET visible = 0
                WHERE diagram_id = ? AND element_id = ?
            ''', (diagram_id, element_id))
            conn.commit()
            
            # Regenerate diagram (similar to POST)
            # ... (regeneration code)
            
        elif request.method == 'PUT':
            # Update element position
            layout_data = request.json.get('layout_data', {})
            x = layout_data.get('x', 0)
            y = layout_data.get('y', 0)
            
            cur = conn.cursor()
            cur.execute('''
                UPDATE composite_diagram_elements
                SET layout_x = ?, layout_y = ?
                WHERE diagram_id = ? AND element_id = ?
            ''', (x, y, diagram_id, element_id))
            conn.commit()
            
            # Regenerate diagram
            # ... (regeneration code)
    finally:
        if conn:
            conn.close()
```

## Phase 3: Chatbot Integration

### 3.1 Enhanced Chatbot Command Detection

```python
def detect_diagram_manipulation_command(question):
    """Detect diagram manipulation commands in chatbot input"""
    question_lower = question.lower()
    
    # Pattern matching for diagram commands
    patterns = {
        'create_element_diagram': [
            r'create.*diagram.*for\s+(\w+)',
            r'show.*diagram.*for\s+(\w+)',
            r'generate.*diagram.*(\w+)'
        ],
        'add_element': [
            r'add\s+(\w+)\s+to\s+(?:the\s+)?diagram',
            r'include\s+(\w+)\s+in\s+(?:the\s+)?diagram',
            r'put\s+(\w+)\s+in\s+(?:the\s+)?diagram'
        ],
        'remove_element': [
            r'remove\s+(\w+)\s+from\s+(?:the\s+)?diagram',
            r'delete\s+(\w+)\s+from\s+(?:the\s+)?diagram',
            r'take\s+(\w+)\s+out\s+of\s+(?:the\s+)?diagram'
        ],
        'create_composite': [
            r'create.*diagram.*(?:showing|with|for)\s+(.+)',
            r'show.*diagram.*(?:of|for)\s+(.+)',
            r'generate.*diagram.*(?:for|with)\s+(.+)'
        ],
        'move_element': [
            r'move\s+(\w+)\s+to\s+(?:the\s+)?(top|bottom|left|right|center)',
            r'position\s+(\w+)\s+at\s+(\d+),\s*(\d+)'
        ],
        'add_relationship': [
            r'connect\s+(\w+)\s+to\s+(\w+)',
            r'link\s+(\w+)\s+and\s+(\w+)',
            r'(\w+)\s+(?:uses|relates|depends on)\s+(\w+)'
        ]
    }
    
    detected_commands = []
    
    for command_type, pattern_list in patterns.items():
        for pattern in pattern_list:
            match = re.search(pattern, question_lower)
            if match:
                detected_commands.append({
                    'type': command_type,
                    'match': match,
                    'groups': match.groups()
                })
    
    return detected_commands

@app.route('/api/chat', methods=['POST'])
def chat():
    """Enhanced chatbot with diagram manipulation"""
    # ... existing code ...
    
    # Check for diagram manipulation commands
    diagram_commands = detect_diagram_manipulation_command(question)
    
    if diagram_commands:
        # Handle diagram commands
        command = diagram_commands[0]  # Take first match
        
        if command['type'] == 'create_element_diagram':
            element_name = command['groups'][0]
            # Find element by name
            # Generate element diagram
            # Return diagram response
            
        elif command['type'] == 'add_element':
            element_name = command['groups'][0]
            # Get current diagram ID from session/context
            # Add element to diagram
            # Regenerate composite
            # Return updated diagram
            
        elif command['type'] == 'remove_element':
            element_name = command['groups'][0]
            # Remove from current diagram
            # Regenerate composite
            # Return updated diagram
            
        elif command['type'] == 'create_composite':
            # Parse element names or facet/enterprise filter
            # Create new composite diagram
            # Return diagram
            
        elif command['type'] == 'move_element':
            # Update element position
            # Regenerate diagram
            # Return updated diagram
            
        elif command['type'] == 'add_relationship':
            source_name = command['groups'][0]
            target_name = command['groups'][1]
            # Find elements
            # Add relationship
            # Regenerate diagram
            # Return updated diagram
    
    # ... continue with normal chatbot flow ...
```

### 3.2 Chatbot Response Format

```python
# Enhanced response format for diagram actions
{
    "type": "diagram_action",
    "action": "add_element|remove_element|create_diagram|update_layout|add_relationship",
    "diagram_id": 123,
    "element_id": 456,
    "element_name": "CustomerPortal",
    "plantuml_code": "...",
    "encoded_url": "...",
    "preview_url": "https://www.plantuml.com/plantuml/png/~1...",
    "message": "Added CustomerPortal to diagram",
    "layout_data": {
        "456": {"x": 100, "y": 100}
    }
}
```

## Phase 4: Frontend UI Components

### 4.1 Element Palette Component

```javascript
function createElementPalette() {
    const palette = document.createElement('div');
    palette.id = 'elementPalette';
    palette.className = 'element-palette';
    
    // Fetch elements
    fetch('/api/records')
        .then(r => r.json())
        .then(elements => {
            elements.forEach(element => {
                const card = createElementCard(element);
                card.draggable = true;
                card.addEventListener('dragstart', (e) => {
                    e.dataTransfer.setData('element_id', element.id);
                    e.dataTransfer.setData('element_name', element.name);
                });
                palette.appendChild(card);
            });
        });
    
    return palette;
}

function createElementCard(element) {
    const card = document.createElement('div');
    card.className = 'element-card';
    card.innerHTML = `
        <div class="element-icon">${getElementIcon(element.element)}</div>
        <div class="element-name">${element.name}</div>
        <div class="element-type">${element.element}</div>
    `;
    return card;
}
```

### 4.2 Diagram Canvas Component

```javascript
function createDiagramCanvas() {
    const canvas = document.createElement('div');
    canvas.id = 'diagramCanvas';
    canvas.className = 'diagram-canvas';
    
    // Enable drop
    canvas.addEventListener('dragover', (e) => {
        e.preventDefault();
        canvas.classList.add('drag-over');
    });
    
    canvas.addEventListener('dragleave', () => {
        canvas.classList.remove('drag-over');
    });
    
    canvas.addEventListener('drop', async (e) => {
        e.preventDefault();
        canvas.classList.remove('drag-over');
        
        const elementId = parseInt(e.dataTransfer.getData('element_id'));
        const elementName = e.dataTransfer.getData('element_name');
        
        // Get drop position
        const rect = canvas.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;
        
        // Add element to diagram
        await addElementToDiagram(currentDiagramId, elementId, x, y);
    });
    
    return canvas;
}

async function addElementToDiagram(diagramId, elementId, x, y) {
    const response = await fetch(`/api/diagrams/${diagramId}/elements/${elementId}`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            layout_data: {x: x, y: y}
        })
    });
    
    const result = await response.json();
    
    // Update diagram display
    updateDiagramDisplay(result);
}
```

### 4.3 Visual Element Rendering

```javascript
function renderElementOnCanvas(element, x, y) {
    const elementDiv = document.createElement('div');
    elementDiv.className = 'canvas-element';
    elementDiv.style.left = x + 'px';
    elementDiv.style.top = y + 'px';
    elementDiv.dataset.elementId = element.id;
    
    elementDiv.innerHTML = `
        <div class="element-header">${element.name}</div>
        <div class="element-type-badge">${element.element}</div>
    `;
    
    // Make draggable
    elementDiv.draggable = true;
    elementDiv.addEventListener('dragstart', (e) => {
        e.dataTransfer.setData('element_id', element.id);
    });
    
    // Position update on drag
    elementDiv.addEventListener('dragend', async (e) => {
        const newX = e.clientX - canvas.offsetLeft;
        const newY = e.clientY - canvas.offsetTop;
        await updateElementPosition(diagramId, element.id, newX, newY);
    });
    
    document.getElementById('diagramCanvas').appendChild(elementDiv);
}
```

## Phase 5: Integration Points

### 5.1 Chatbot UI Integration

```javascript
// In chatbot message handler
function handleChatbotDiagramAction(action) {
    if (action.type === 'diagram_action') {
        // Switch to diagram view
        showSection('diagramView');
        
        // Update diagram
        displayPlantUMLDiagram(
            action.plantuml_code,
            action.encoded_url,
            action.elements_count || 0,
            action.relationships_count || 0,
            action.title || 'Diagram',
            [],
            null,
            action.element_ids || [],
            'composite',
            action.diagram_id
        );
        
        // Show success message
        addChatMessage(action.message, 'assistant');
    }
}
```

### 5.2 Diagram Editor Integration

```javascript
// New diagram editor section
function showDiagramEditor(diagramId) {
    showSection('diagramEditor');
    
    // Load diagram
    fetch(`/api/diagrams/${diagramId}`)
        .then(r => r.json())
        .then(diagram => {
            // Render palette
            const palette = createElementPalette();
            document.getElementById('editorSidebar').appendChild(palette);
            
            // Render canvas
            const canvas = createDiagramCanvas();
            document.getElementById('editorMain').appendChild(canvas);
            
            // Load existing elements
            if (diagram.layout_data) {
                const layout = JSON.parse(diagram.layout_data);
                Object.keys(layout).forEach(elementId => {
                    const pos = layout[elementId];
                    // Render element at position
                });
            }
        });
}
```

## Next Steps

1. **Implement Phase 1**: Database schema migration
2. **Implement Phase 2**: Backend API endpoints
3. **Implement Phase 3**: Chatbot integration
4. **Implement Phase 4**: Frontend UI components
5. **Test**: End-to-end testing of drag-and-drop flow
6. **Refine**: UI/UX improvements based on testing

---

*This plan provides a concrete roadmap for implementing drag-and-drop modeling with PlantUML embedding.*

