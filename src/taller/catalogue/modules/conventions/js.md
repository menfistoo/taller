> JavaScript naming, module and DOM rules, including why markup is queried by data attributes.

## Naming and syntax

`camelCase` for variables and functions, `PascalCase` for classes and constructors,
`UPPER_SNAKE` for module constants. `const` by default, `let` when a value genuinely
changes, `var` never - its function scoping and hoisting mean a declaration inside a
block is visible outside it, which is a bug waiting for a refactor.

Use strict equality (`===`). Loose equality applies a coercion table nobody
remembers, and the two cases where it is convenient are not worth the one case where
it is silently wrong.

Async work uses `async`/`await` with a `try`/`catch`, not chained callbacks. An
awaited call that can fail and has no catch produces an unhandled rejection, which in
a browser means the feature stops with nothing on screen and nothing in the log.

## Modules

Code is organised as ES modules with explicit `import`/`export`, loaded with
`<script type="module">`. No globals: a function attached to `window` can be
overwritten by any other script on the page, and its callers become impossible to
enumerate. Modules are deferred by default, so the DOM already exists when the
module body runs and no load-event wrapper is needed.

One module per concern, named for it. A module that imports nothing and is imported
by nothing is dead and should be deleted rather than kept "for later".

## Talking to the DOM

**Query by a `data-*` attribute, never by a class name.** Classes exist for styling,
and styling changes for visual reasons by people who are not reading the JavaScript.
A selector on `.btn-primary` breaks the moment a designer changes the emphasis of a
button, and the break is silent. `[data-action="submit-order"]` states that the
markup is referenced by code, so it survives restyling and shows up in a search.

**Write text with `textContent`, not `innerHTML`.** Any value that came from a user,
a file or an API becomes executable markup when assigned to `innerHTML`, and this is
the most common injection path in a browser. When structure really is needed, build
elements and set their properties.

Attach one listener to a stable container and read the event target when the same
handler serves many elements, so content added later needs no rebinding.

## Failure has to be visible

**Every state a user can be in needs something on screen:** loading, empty, and
failed. A fetch that rejects must put a readable message in the interface, not only
in the console, because the person affected is not looking at the console. A silent
failure is indistinguishable from a broken build, and it is reported to you as
"it doesn't work", with no detail, days later.
