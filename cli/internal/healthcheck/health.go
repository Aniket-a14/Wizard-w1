// Package healthcheck polls the backend's existing GET /health and
// GET /api/config routes. Nothing here reimplements what those routes
// already report (host sizing, sandbox capability, execution backend, ...)
// -- see backend/src/api/routes/meta.py -- it only fetches and decodes them.
package healthcheck

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"
)

// Health mirrors the fields of HealthResponse in backend/src/api/schemas.py
// that the CLI actually uses.
type Health struct {
	Status           string `json:"status"`
	Version          string `json:"version"`
	SandboxAvailable bool   `json:"sandbox_available"`
	ExecutionBackend string `json:"execution_backend"`
	ModelProvider    string `json:"model_provider"`
}

// Config is GET /api/config, decoded generically. ServerConfig in
// backend/src/api/schemas.py has dozens of fields and grows over time; a
// generic map means `wizard status`/`doctor` render whatever the backend
// reports without this binary needing a matching struct field for each one.
type Config map[string]any

// Client talks to one backend base URL (e.g. http://127.0.0.1:8000).
type Client struct {
	BaseURL string
	HTTP    *http.Client
}

func NewClient(baseURL string) *Client {
	return &Client{BaseURL: baseURL, HTTP: &http.Client{Timeout: 5 * time.Second}}
}

func (c *Client) get(ctx context.Context, path string, out any) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, c.BaseURL+path, nil)
	if err != nil {
		return err
	}
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
		return fmt.Errorf("%s returned %s: %s", path, resp.Status, string(body))
	}
	return json.NewDecoder(resp.Body).Decode(out)
}

// Health fetches GET /health.
func (c *Client) Health(ctx context.Context) (*Health, error) {
	var h Health
	if err := c.get(ctx, "/health", &h); err != nil {
		return nil, err
	}
	return &h, nil
}

// ServerConfig fetches GET /api/config.
func (c *Client) ServerConfig(ctx context.Context) (Config, error) {
	var cfg Config
	if err := c.get(ctx, "/api/config", &cfg); err != nil {
		return nil, err
	}
	return cfg, nil
}

// WaitHealthy polls GET /health until it answers or the timeout elapses,
// returning the last error on timeout. Used by `wizard start` to know when
// the backend it just launched is ready to be handed to the browser -- and
// by nothing else, since a supervisor's steady-state polling wants its own
// shorter, indefinitely-repeating loop, not a bounded wait.
func (c *Client) WaitHealthy(ctx context.Context, timeout, interval time.Duration) (*Health, error) {
	deadline := time.Now().Add(timeout)
	var lastErr error
	for {
		h, err := c.Health(ctx)
		if err == nil && h.Status == "ok" {
			return h, nil
		}
		if err != nil {
			lastErr = err
		} else {
			lastErr = fmt.Errorf("status %q", h.Status)
		}
		if time.Now().After(deadline) {
			return nil, fmt.Errorf("backend did not become healthy within %s: %w", timeout, lastErr)
		}
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		case <-time.After(interval):
		}
	}
}
