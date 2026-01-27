# PlantUML Case Sensitivity Fix

## Issue
PlantUML `$link` generation was inconsistent with case-sensitive syntax rules for element names. Some code paths were converting element names to lowercase, which could cause mismatches between element declarations and link statements.

## Changes Made

### 1. Element Variable Name Creation (Lines 1813-1828)
- **Before**: Code preserved case but comments weren't explicit about case sensitivity
- **After**: Enhanced comments to explicitly state "Preserve original case exactly as provided (case-sensitive)"
- **Impact**: Ensures element variable names stored in `element_map` maintain original case

### 2. Element Variable Name Fallback (Lines 1876-1877 and 2003-2004)
- **Before**: Used `str(capitalized_name).lower().replace(" ", "_")` which converted to lowercase
- **After**: Uses case-preserving sanitization:
  ```python
  fallback_name = str(capitalized_name).replace(" ", "_").replace("-", "_")
  fallback_name = ''.join(c if c.isalnum() or c == '_' else '' for c in fallback_name)
  if fallback_name and not fallback_name[0].isalpha():
      fallback_name = 'E' + fallback_name
  element_var_name = element_map.get(elem_id, fallback_name or "Element")
  ```
- **Impact**: Fallback variable names now preserve case, matching the primary `element_map` values

### 3. Relationship Link Generation (Lines 2114-2128)
- **Before**: Code preserved case but comments weren't explicit
- **After**: Enhanced comments to explicitly state "Preserve case - do not lowercase or capitalize"
- **Impact**: Ensures `$link` statements use exact same variable names as element declarations

## Key Principles

1. **Case Preservation**: Element names are sanitized but case is preserved throughout
2. **Consistency**: Same sanitization logic used in all code paths
3. **PlantUML Compatibility**: Variable names match exactly between element declarations and `$link` statements

## Testing Recommendations

1. Test with mixed-case element names (e.g., "CustomerPortal", "API_Gateway")
2. Verify `$link` statements use exact same variable names as element declarations
3. Test Product, Organisation, and Brand elements (which use fixed lowercase names)
4. Test other element types with various case combinations

## Example

**Element Name**: "CustomerPortal"
- **Sanitized Variable**: "CustomerPortal" (preserves case)
- **Element Declaration**: `$capability("CustomerPortal")`
- **Link Statement**: `$link(CustomerPortal, OtherElement, "relates")`

**Element Name**: "API Gateway"
- **Sanitized Variable**: "API_Gateway" (preserves case, replaces space)
- **Element Declaration**: `$capability("API Gateway")`
- **Link Statement**: `$link(API_Gateway, OtherElement, "relates")`

---

*Fixed: All PlantUML link generation now consistently handles case-sensitive element names*

