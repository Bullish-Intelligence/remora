; Standard imports: import foo, import foo.bar
(import_statement
  name: (dotted_name) @import.target) @import

; From imports: from foo import bar
(import_from_statement
  module_name: (dotted_name) @import.source
  name: (dotted_name) @import.target) @import

; From imports with alias: from foo import bar as baz
(import_from_statement
  module_name: (dotted_name) @import.source
  name: (aliased_import
    name: (dotted_name) @import.target)) @import
