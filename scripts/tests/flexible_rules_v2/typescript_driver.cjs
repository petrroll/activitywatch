#!/usr/bin/env node
'use strict';

// Load the checkout's real TypeScript sources without adding another runtime
// dependency. TypeScript's transpileModule is sufficient because the WebUI
// query/compiler modules are ordinary TS and type checking remains in WebUI CI.
const fs = require('fs');
const path = require('path');
const Module = require('module');

const repo = path.resolve(__dirname, '../../..');
const webui = path.join(repo, 'aw-server', 'aw-webui');
const ts = require(path.join(webui, 'node_modules', 'typescript'));
const originalResolve = Module._resolveFilename;
Module._resolveFilename = function (request, parent, isMain, options) {
  if (request.startsWith('~/')) request = path.join(webui, 'src', request.slice(2));
  return originalResolve.call(this, request, parent, isMain, options);
};
require.extensions['.ts'] = function (module, filename) {
  const source = fs.readFileSync(filename, 'utf8');
  const output = ts.transpileModule(source, {
    fileName: filename,
    compilerOptions: {
      target: ts.ScriptTarget.ES2020,
      module: ts.ModuleKind.CommonJS,
      moduleResolution: ts.ModuleResolutionKind.NodeJs,
      esModuleInterop: true,
    },
  });
  module._compile(output.outputText, filename);
};

function usage() {
  console.error('usage: node typescript_driver.cjs FIXTURES.json OUTPUT.json');
  process.exit(2);
}
if (process.argv.length !== 4) usage();

const inputPath = path.resolve(process.argv[2]);
const outputPath = path.resolve(process.argv[3]);
const corpus = JSON.parse(fs.readFileSync(inputPath, 'utf8'));
const queries = require(path.join(webui, 'src', 'queries.ts'));
const rules = require(path.join(webui, 'src', 'util', 'rulesV2.ts'));
const materialize = require(path.join(webui, 'src', 'util', 'materializeV2.ts'));
const classes = require(path.join(webui, 'src', 'util', 'classes.ts'));

function bucketMetadata(fixture) {
  return fixture.buckets.map(bucket => ({
    id: bucket.id,
    type: bucket.type,
    client: bucket.client,
    hostname: bucket.hostname,
    created: bucket.created || '2024-01-01T00:00:00Z',
    data: bucket.data || {},
  }));
}

function canonicalOptions(fixture) {
  const options = JSON.parse(JSON.stringify(fixture.options));
  options.capabilities = [...corpus.capabilities];
  if (options.filter_categories === undefined) options.filter_categories = null;
  return options;
}

function migratedProfileDocument(contract) {
  if (!contract.legacy_settings) return contract.document;
  const settings = contract.legacy_settings;
  if (Array.isArray(settings.activity_profiles_v2) && Array.isArray(settings.category_sets_v2)) {
    const resolved = rules.resolveRulesV2Settings({
      activity_profiles_v2: settings.activity_profiles_v2,
      category_sets_v2: settings.category_sets_v2,
      classes: Array.isArray(settings.classes) ? settings.classes : classes.defaultCategories,
      always_active_pattern: settings.always_active_pattern || '',
    });
    return {...resolved, revision: 0};
  }
  const defaults = rules.migrateLegacySettings({
    classes: Array.isArray(settings.classes) ? settings.classes : classes.defaultCategories,
    always_active_pattern: settings.always_active_pattern || '',
  });
  if (!Array.isArray(settings.category_sets) || settings.category_sets.length === 0) {
    return {...defaults, revision: 0};
  }
  const legacySets = settings.category_sets
    .filter(set => set && typeof set.id === 'string' && Array.isArray(set.categories))
    .map(set => ({id: set.id, categories: set.categories.map(classes.cleanCategory)}));
  const migrated = rules.migrateLegacyCategorySets(
    legacySets,
    Array.isArray(settings.active_set_ids)
      ? settings.active_set_ids.filter(id => typeof id === 'string')
      : []
  );
  defaults.activity_profiles_v2[0].category_set_ids = migrated.activeSetIds;
  defaults.category_sets_v2 = migrated.categorySets;
  return {...defaults, revision: 0};
}

function profileOptions(fixture) {
  const contract = fixture.profile_contract;
  if (!contract) return null;
  const document = migratedProfileDocument(contract);
  const profile = document.activity_profiles_v2.find(p => p.id === contract.selected_profile_id);
  if (!profile) throw new Error(`profile ${contract.selected_profile_id} is absent`);
  const compiled = rules.compileActivityQueryV2(
    profile,
    document.category_sets_v2,
    corpus.capabilities
  );
  const buckets = bucketMetadata(fixture);
  const options = materialize.materializeActivityQueryV2({
    compiled,
    buckets,
    host: fixture.options.hostname,
    filterAfk: fixture.options.filter_afk,
    filterCategories: fixture.options.filter_categories ?? null,
    explainCategories: fixture.options.explain_categories ?? false,
    includeAudible: fixture.options.include_audible,
    browserBucketIds:
      fixture.options.browser_bucket_ids ??
      fixture.buckets.filter(bucket => bucket.type === 'web.tab.current').map(bucket => bucket.id),
  });
  return {compiled, buckets, options};
}

function resultSuffix(fixture) {
  if (fixture.result_variables === 'suffix') {
    const suffix = fixture.legacy_options.return_variable_suffix;
    return `\nRETURN = [events_${suffix}, not_afk_${suffix}];`;
  }
  if (fixture.return_browser) {
    return '\nRETURN = {"events": events, "active": not_afk, "browser": browser_events, "browser_duration": sum_durations(browser_events)};';
  }
  return '\nRETURN = [events, not_afk];';
}

const output = {schema_version: 1, builder: 'typescript', queries: {}, options: {}};
for (const fixture of corpus.fixtures) {
  try {
    if (fixture.supported_builders && !fixture.supported_builders.includes('typescript')) {
      throw new Error('fixture does not apply to the TypeScript builder');
    }
    if (fixture.builder_mode === 'typescript_multidevice') {
      const options = JSON.parse(JSON.stringify(fixture.legacy_options));
      options.categories = options.classes || [];
      delete options.classes;
      if (!(fixture.omit_capabilities_for || []).includes('typescript')) {
        options.capabilities = [...corpus.capabilities];
      }
      output.options[fixture.id] = options;
      output.queries[fixture.id] = queries.multideviceQuery(options).join('\n') + resultSuffix(fixture);
      continue;
    }
    if (fixture.builder_mode === 'legacy_desktop') {
      const options = JSON.parse(JSON.stringify(fixture.legacy_options));
      options.categories = options.classes || [];
      delete options.classes;
      if (!(fixture.omit_capabilities_for || []).includes('typescript')) {
        options.capabilities = [...corpus.capabilities];
      }
      output.options[fixture.id] = options;
      const query =
        fixture.legacy_variant === 'full_desktop'
          ? queries.fullDesktopQuery(options).join('\n')
          : queries.canonicalEvents(options);
      output.queries[fixture.id] = query + resultSuffix(fixture);
      continue;
    }
    // Profile fixtures intentionally travel through the real document compiler
    // and host/bucket materializer rather than trusting pre-expanded options.
    const profile = profileOptions(fixture);
    const options = profile ? profile.options : canonicalOptions(fixture);
    output.options[fixture.id] = options;
    if (fixture.builder_mode === 'typescript_activity_report') {
      const reportOptions = {
        ...options,
        app_title_source_id: profile.compiled.app_title_source_id,
        browser_focus_source_id: profile.compiled.browser_focus_source_id,
        browser_source: materialize.materializeConfiguredBrowserSource(
          profile.compiled,
          profile.buckets,
          fixture.options.hostname
        ),
      };
      output.queries[fixture.id] =
        queries.fullActivityQueryV2(reportOptions).join('\n') + resultSuffix(fixture);
    } else {
      output.queries[fixture.id] = queries.canonicalEventsV2(options) + resultSuffix(fixture);
    }
  } catch (error) {
    output.queries[fixture.id] = {error: String(error && error.stack ? error.stack : error)};
  }
}
fs.writeFileSync(outputPath, JSON.stringify(output, null, 2) + '\n');
