{
 "method": "DELETE",
 "path": "/api/v1/vendor/{value}",
 "query": {},
 "body": null,
 "values_sql": "BEGIN READ ONLY; SELECT v.id FROM vendor v JOIN filament f ON f.vendor_id = v.id JOIN spool s ON s.filament_id = f.id GROUP BY v.id ORDER BY v.id; COMMIT;",
 "why": "Deleting a vendor loads its filaments and then reads spool by filament_id to load each filament's spools.",
 "table": "spool",
 "column": "filament_id"
}