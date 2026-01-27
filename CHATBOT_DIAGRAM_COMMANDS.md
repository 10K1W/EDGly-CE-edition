# Chatbot Diagram Commands Reference

## Overview

The enhanced chatbot will understand natural language commands for diagram manipulation, enabling users to create and modify diagrams through conversation.

## Command Patterns

### 1. Create Element Diagram

**Patterns:**
- "Create a diagram for [ElementName]"
- "Show diagram for [ElementName]"
- "Generate diagram for [ElementName]"
- "Display [ElementName] diagram"

**Examples:**
```
User: "Create a diagram for CustomerPortal"
Bot: [Generates single-element diagram, shows preview]

User: "Show diagram for PaymentGateway"
Bot: [Shows element diagram with properties]
```

**Implementation:**
```python
if re.search(r'create.*diagram.*for\s+(\w+)', question, re.IGNORECASE):
    element_name = match.group(1)
    # Find element, generate diagram, return preview
```

### 2. Add Element to Diagram

**Patterns:**
- "Add [ElementName] to the diagram"
- "Include [ElementName] in the diagram"
- "Put [ElementName] in the diagram"
- "Add [ElementName]"

**Examples:**
```
User: "Add PaymentGateway to the diagram"
Bot: [Adds element, updates composite, shows updated diagram]

User: "Include API Gateway"
Bot: [Finds API Gateway, adds to current diagram]
```

**Context Required:**
- Current diagram ID (from session or explicit reference)
- Element name or ID

**Implementation:**
```python
if re.search(r'add\s+(\w+)\s+to\s+(?:the\s+)?diagram', question, re.IGNORECASE):
    element_name = match.group(1)
    # Find element, add to current diagram, regenerate composite
```

### 3. Remove Element from Diagram

**Patterns:**
- "Remove [ElementName] from the diagram"
- "Delete [ElementName] from the diagram"
- "Take [ElementName] out of the diagram"
- "Remove [ElementName]"

**Examples:**
```
User: "Remove PaymentGateway from the diagram"
Bot: [Removes element, updates diagram]

User: "Delete CustomerPortal"
Bot: [Removes from current diagram context]
```

### 4. Create Composite Diagram

**Patterns:**
- "Create a diagram showing [description]"
- "Show diagram of [elements/facet/enterprise]"
- "Generate diagram for [criteria]"
- "Create diagram with [elements]"

**Examples:**
```
User: "Create a diagram showing all Architecture capabilities"
Bot: [Creates composite with all Architecture elements]

User: "Show diagram of CustomerPortal and PaymentGateway"
Bot: [Creates composite with specified elements]

User: "Generate diagram for AcmeCorp enterprise"
Bot: [Creates composite with all AcmeCorp elements]
```

**Implementation:**
```python
if re.search(r'create.*diagram.*(?:showing|with|for)\s+(.+)', question, re.IGNORECASE):
    criteria = match.group(1)
    # Parse criteria (facet, enterprise, element names)
    # Create composite diagram
```

### 5. Move/Position Element

**Patterns:**
- "Move [ElementName] to the [position]"
- "Position [ElementName] at [x], [y]"
- "Place [ElementName] [position]"

**Positions:**
- top, bottom, left, right, center
- Coordinates: "at 100, 200"

**Examples:**
```
User: "Move CustomerPortal to the top left"
Bot: [Updates position, regenerates diagram]

User: "Position PaymentGateway at 300, 150"
Bot: [Sets exact coordinates]
```

### 6. Add Relationship

**Patterns:**
- "Connect [Element1] to [Element2]"
- "Link [Element1] and [Element2]"
- "[Element1] uses [Element2]"
- "[Element1] relates to [Element2]"

**Relationship Types:**
- Detected from context: "uses", "relates", "depends on", "implements"
- Default: "relates"

**Examples:**
```
User: "Connect CustomerPortal to PaymentGateway"
Bot: [Adds relationship, updates diagram]

User: "CustomerPortal uses PaymentGateway"
Bot: [Adds "uses" relationship]

User: "Link API Gateway and Database"
Bot: [Adds relationship between elements]
```

### 7. Modify Diagram Properties

**Patterns:**
- "Show properties for [ElementName]"
- "Add properties to [ElementName]"
- "Update [ElementName] description"

**Examples:**
```
User: "Show properties for CustomerPortal"
Bot: [Displays element properties in diagram notes]

User: "Add notes to the diagram"
Bot: [Regenerates diagram with notes included]
```

## Context Management

### Diagram Context
The chatbot maintains context about:
- **Current Diagram**: ID of the active diagram being modified
- **Session State**: Last diagram created/modified
- **Element References**: Recently mentioned elements

### Context Detection
```python
# Detect diagram context from conversation
def get_current_diagram_context():
    # Check for explicit diagram ID in message
    # Check session state for last diagram
    # Check for diagram title references
    return diagram_id or None
```

### Context Switching
```python
# User can switch context
"Work on the Architecture diagram"
"Switch to the Customer Journey diagram"
"Show me the Payment System diagram"
```

## Response Format

### Diagram Action Response
```json
{
    "type": "diagram_action",
    "action": "add_element",
    "diagram_id": 123,
    "element_id": 456,
    "element_name": "CustomerPortal",
    "plantuml_code": "@startuml\n...",
    "encoded_url": "...",
    "preview_url": "https://www.plantuml.com/plantuml/png/~1...",
    "message": "Added CustomerPortal to the diagram",
    "layout_data": {
        "456": {"x": 100, "y": 100}
    },
    "elements_count": 5,
    "relationships_count": 3
}
```

### Error Response
```json
{
    "type": "error",
    "error": "Element 'XYZ' not found",
    "suggestions": [
        "Did you mean 'CustomerPortal'?",
        "Available elements: CustomerPortal, PaymentGateway..."
    ]
}
```

## Advanced Commands

### Batch Operations
```
"Add CustomerPortal, PaymentGateway, and API Gateway to the diagram"
"Remove all Architecture elements"
"Create diagram with all elements from AcmeCorp"
```

### Conditional Operations
```
"If CustomerPortal exists, add it to the diagram"
"Show diagram only if it has more than 5 elements"
```

### Query Operations
```
"What elements are in the current diagram?"
"Show me all relationships in the diagram"
"List all diagrams for AcmeCorp"
```

## Implementation Strategy

### Phase 1: Basic Commands
1. Create element diagram
2. Create composite diagram
3. Add element to diagram

### Phase 2: Manipulation Commands
1. Remove element
2. Move element
3. Add relationship

### Phase 3: Advanced Features
1. Context management
2. Batch operations
3. Query operations
4. Error handling and suggestions

## Example Conversation Flow

```
User: "Create a diagram for CustomerPortal"
Bot: [Shows element diagram]

User: "Add PaymentGateway to it"
Bot: [Creates composite, adds PaymentGateway]

User: "Connect them with a 'uses' relationship"
Bot: [Adds relationship, updates diagram]

User: "Move CustomerPortal to the top"
Bot: [Updates layout, regenerates]

User: "Add API Gateway"
Bot: [Adds element, updates diagram]

User: "Show me the diagram"
Bot: [Displays full composite diagram]
```

## Natural Language Processing

### Element Name Resolution
- Fuzzy matching for element names
- Suggestions for similar names
- Case-insensitive matching
- Partial name matching

### Intent Classification
- Use LLM to classify user intent
- Extract entities (element names, positions, relationship types)
- Handle ambiguous requests

### Error Recovery
- Suggest corrections for typos
- Offer alternatives when element not found
- Clarify ambiguous requests

---

*This reference guide helps implement natural language diagram manipulation in the chatbot.*

