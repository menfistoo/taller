> Hand-written HTML, CSS and JavaScript served as files, with no build step at all.

## Runtime shape

The deployable artefact is the repository: HTML files at the root, CSS and JS beside
them, images in a folder. Any static file server can serve it, and opening a file
from disk in a browser works too. There is no bundler, no transpiler, no package
manager in the serving path, and no server-side code.

## No build step is a feature, not an omission

The absence of a build is the property this stack exists for. What is in the
repository is exactly what a visitor receives, so a reviewer diffing a change sees
the shipped result, and nobody has to reproduce a toolchain years later to fix a
typo. Introducing a bundler ends that guarantee for every file, not just the new
one, so it is a decision for a ticket of its own and never a side effect.

This means the code must be written for the browser as it is: ES modules loaded with
`<script type="module">`, CSS custom properties instead of a preprocessor, and no
syntax that would need compiling. Modern browsers cover all of it.

## The optional Python helper

Some pages are driven by data that is tedious to maintain by hand. A helper script
may prepare it, under two rules.

**The helper writes data files only.** It emits JSON or CSV that the page fetches,
and never HTML, CSS or JS. Once a script generates markup, the repository stops
being the shipped result and this stack has quietly acquired a build step.

**Its output is committed.** The site must remain serveable by someone who has no
Python installed and no idea the helper exists. A generated file that is missing
from the repository turns a static site into a pipeline.

The helper is run by hand when the source data changes, is deterministic given the
same input, and depends on the standard library where it can.

## Failure and links

A page fetching a data file must render something useful when the fetch fails,
because a file server returning 404 for a renamed file is the normal failure here
and a blank page gives the reader nothing to report. Links between pages are
relative, so the site works from a subdirectory and from disk.
