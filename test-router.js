/**
 * Quick test of router tool registry
 * Run with: node test-router.js
 */

import { getAllCategories, searchTools, getRegistryStats, isDirectTool } from './dist/tools/registry.js';

console.log('='.repeat(70));
console.log('KICAD MCP ROUTER - TEST');
console.log('='.repeat(70));

// Test 1: Registry Stats
console.log('\n📊 Registry Statistics:');
const stats = getRegistryStats();
console.log(JSON.stringify(stats, null, 2));

// Test 2: List Categories
console.log('\n📁 Tool Categories:');
const categories = getAllCategories();
categories.forEach(cat => {
  console.log(`  - ${cat.name}: ${cat.description} (${cat.tools.length} tools)`);
});

// Test 3: Search
console.log('\n🔍 Search Test: "export gerber"');
const results = searchTools('gerber');
console.log(`Found ${results.length} matches:`);
results.forEach(result => {
  console.log(`  - ${result.tool} (${result.category})`);
});

// Test 4: Direct Tools Check
console.log('\n✅ Direct Tools Test:');
console.log(`  - create_project is direct: ${isDirectTool('create_project')}`);
console.log(`  - place_component is direct: ${isDirectTool('place_component')}`);
console.log(`  - export_gerber is direct: ${isDirectTool('export_gerber')}`);
console.log(`  - add_via is direct: ${isDirectTool('add_via')}`);

console.log('\n' + '='.repeat(70));
console.log('✅ Router tests complete!');
console.log('='.repeat(70));
