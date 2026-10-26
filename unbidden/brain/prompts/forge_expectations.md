You prepare the tests for a log parser before anyone writes it.

Below are numbered lines from a service's log. For each of the first five that records an HTTP request, write
what a correct parser must extract: the HTTP method, the request path (without the query string's host part,
exactly as it appears), and the numeric status code. Copy values exactly as they appear in the line.

Answer with JSON only, matching this schema: {{schema}}

Log lines:
{{lines}}
