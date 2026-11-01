{
 "method": "DELETE",
 "path": "/api/v1/vendor/{value}",
 "query": {},
 "body": null,
 "values_sql": "BEGIN READ ONLY; SELECT DISTINCT f.vendor_id FROM filament f JOIN spool s ON s.filament_id = f.id WHERE f.vendor_id IS NOT NULL ORDER BY f.vendor_id LIMIT 100; COMMIT;",
 "why": "Deleting a vendor loads its filaments and then reads spool by filament_id to resolve dependent spools.",
 "table": "spool",
 "column": "filament_id"
}