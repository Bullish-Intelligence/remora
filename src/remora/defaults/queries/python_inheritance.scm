; Class with simple base: class Foo(Bar)
(class_definition
  name: (identifier) @class.name
  superclasses: (argument_list
    (identifier) @class.base)) @class

; Class with dotted base: class Foo(bar.Baz)
(class_definition
  name: (identifier) @class.name
  superclasses: (argument_list
    (attribute
      object: (identifier)
      attribute: (identifier) @class.base))) @class
