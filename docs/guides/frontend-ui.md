# Frontend and UI Guide

## Frontend Stack

- Server-rendered Django templates are the primary rendering model.
- HTMX handles backend-driven interactions.
- Alpine.js handles browser-only interaction state.
- Tailwind v4 + DaisyUI provide the design system baseline.

## Asset Loading Rules

- JavaScript/CSS built by Vite should be loaded with `django-vite` template tags.
- Use `{% static %}` for non-Vite assets only.
- Keep page scripts out of inline `<script>` blocks when possible.

## Template Conventions

- Two-space indentation in HTML templates.
- Use translation tags for user-facing text.
- Extract reusable chunks into component partials.

## JavaScript Conventions

- ES6+ syntax, semicolons, single quotes.
- 2-space indentation.
- Camel case for variables/functions, Pascal case for components.
- Use generated API client for API calls instead of ad hoc fetch logic.

## Change Guidance

- Preserve existing UX and template patterns unless explicitly redesigning.
- Prefer incremental HTMX/Alpine enhancements over introducing a new frontend framework.
