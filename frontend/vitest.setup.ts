import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

// Testing Library only unmounts automatically when Vitest globals are enabled.
// This project imports its test helpers explicitly instead, so the teardown has
// to be wired up by hand — without it, every test renders into a document still
// holding the previous test's component, and queries start matching two of
// everything.
afterEach(cleanup);
