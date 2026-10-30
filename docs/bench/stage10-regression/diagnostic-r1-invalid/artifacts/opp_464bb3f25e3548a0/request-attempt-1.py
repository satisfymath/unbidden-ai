{
 "method": "DELETE",
 "path": "/api/v1/vendor/{value}",
 "query": {},
 "body": null,
 "values_sql": "BEGIN READ ONLY; SELECT id FROM vendor ORDER BY id; COMMIT;",
 "why": "Deleting a vendor loads its filaments and then reads spool by filament_id for each filament.",
 "table": "spool",
 "column": "filament_id"
}