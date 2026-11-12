import { beforeEach } from 'vitest'

// The project chip choice lives in localStorage; every test starts from "All projects".
beforeEach(() => localStorage.clear())
