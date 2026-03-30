; Top-level and nested function definitions.
(function_definition
  name: (identifier) @node.name) @node

; Class definitions.
(class_definition
  name: (identifier) @node.name) @node

; Decorated function definitions.
(decorated_definition
  definition: (function_definition
    name: (identifier) @node.name)) @node

; Decorated class definitions.
(decorated_definition
  definition: (class_definition
    name: (identifier) @node.name)) @node
