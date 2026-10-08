# Deploy the builtin cleanup

The source change removes builtin image/table operators and the Sequence family.
It adds `plugins/image` and `plugins/table` as independent publication inputs.
It does not delete stored graphs, artifacts, or retained Plugin releases.

1. Back up PostgreSQL and the exact System selection rows. Keep the currently
   deployed image references with the backup.
2. Audit current graph documents, collaborative heads, templates, and retained
   revisions. For exported `SavedGraphDocument` JSON files, run:

   ```console
   uv run python scripts/audit_builtin_cleanup.py graph-document.json
   ```

   The report omits node configuration and performs no writes. A Collect node
   with incoming edges requires a deliberate graph redesign. Static card
   grouping must not silently replace live dependencies.
3. Remove old selections whose file-format dependencies still declare JSON
   bundles. Keep their immutable releases. `revoke` is not an unregister command:
   it permanently denies a release and does not remove its catalog selection.
4. Deploy the reviewed application's published image using the production
   deployment guide. Do not mix new Plugins with the old application: builtin
   `image.decode@1` and `table.import@1` reserve those operator identities.
5. Publish and promote `plugins/image` as `external.image` and `plugins/table` as
   `external.table`, following the Plugin publication guide. Republish any other
   retained Plugin that depends on the old `file.*` contracts before selecting it.
6. Reinsert image/table nodes through the Workbench with exact Plugin release
   pins. Rebuild removed sequence operations with artifact-card Collect where
   applicable. Verify a representative file upload and graph run.

For rollback, restore the old application images and backed-up selections
before reopening old graph documents. Do not rewrite old release manifests.

See [ADR 0013](adr/0013-specialized-file-operators-are-published-plugins.md),
[production deployment](how-to-deploy-production.md), and
[Plugin publication](how-to-publish-plugins.md).
