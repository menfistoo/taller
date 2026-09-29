> Bootstrap 5 conventions: tokens before values, framework components before bespoke ones.

## Tokens before literal values

**Never write a colour, a font or a spacing value literally in a template or a
stylesheet.** Use the project's design tokens. A literal value is invisible to every
future change: a palette adjustment finds the tokens and misses the hex code someone
typed in a template, so the interface drifts one hardcoded value at a time and the
drift is only ever noticed by a person looking at two screens side by side.

If no token fits, that is a gap in the token set and it is worth saying so in the
ticket. Inventing a value in place is how a design system stops describing the
product.

## Framework components before bespoke ones

Use the framework's own components and utilities before writing your own. They carry
keyboard handling, focus management and the ARIA attributes that assistive
technology needs, all of which are easy to omit and invisible in a screenshot. A
bespoke dropdown looks finished and fails for anyone not using a mouse.

Compose with utility classes rather than adding a new custom class for each
variation. Custom CSS is for what the framework genuinely cannot express, and every
rule of it is a rule someone must later reconcile with a framework upgrade.

## Real controls

**Something that performs an action is a `<button>`; something that navigates is an
`<a>` with an `href`.** A clickable `<div>` is not focusable, is not reachable by
keyboard, is not announced as a control, and does not respond to the space bar. It
looks identical and excludes people. Never reach for `role="button"` on a `<div>` to
patch this up: the element that already behaves correctly exists.

## Small screens are the default case

Design the narrow layout first and let wider viewports be the enhancement. Most
interfaces are used on a phone more often than their authors expect, and a layout
built wide first fails narrow in ways that cannot be fixed with a breakpoint.
Touch targets stay comfortably large; nothing important depends on hovering, because
there is no hover on a touch screen.

## Accessibility is not a later pass

Every input has a real `<label>` bound to it; a placeholder is not a label, since it
disappears exactly when the user needs it. Every meaningful image has alt text, and
every decorative one has empty alt text so a screen reader skips it. Text contrast
meets WCAG AA, which is a measured ratio and not a judgement. Colour is never the
only carrier of meaning: add a word or an icon beside it.

## Language

**Every string the user reads is written in the project's configured UI language**,
including validation messages, empty states and button labels. Identifiers, comments
and commit messages follow the project's code language instead. Mixing the two
produces an interface that reads as half-finished, and the mixture is never noticed
by the person who wrote it.
