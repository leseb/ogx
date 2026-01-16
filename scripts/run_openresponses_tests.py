#!/usr/bin/env python3
"""
Script to programmatically run Open Responses compliance tests.

This script automates the browser interaction with https://www.openresponses.org/compliance
to trigger the "Run All Tests" button programmatically.

Usage:
    python scripts/run_openresponses_tests.py \
        --base-url http://localhost:8000 \
        --model llama-3.1-8b \
        --api-key your-api-key \
        --auth-header-name Authorization \
        --use-bearer-prefix

Alternatively, you can use environment variables:
    export OPENRESPONSES_BASE_URL=http://localhost:8000
    export OPENRESPONSES_MODEL=llama-3.1-8b
    export OPENRESPONSES_API_KEY=your-api-key
    python scripts/run_openresponses_tests.py
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

try:
    from playwright.async_api import Page, async_playwright
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError
except ImportError:
    print(
        "Error: playwright is not installed. Install it with:\n"
        "  uv pip install playwright\n"
        "  playwright install chromium",
        file=sys.stderr,
    )
    sys.exit(1)


class OpenResponsesTestRunner:
    """Runner for Open Responses compliance tests using browser automation."""

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str,
        auth_header_name: str = "Authorization",
        use_bearer_prefix: bool = True,
        headless: bool = True,
        timeout: int = 300,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.auth_header_name = auth_header_name
        self.use_bearer_prefix = use_bearer_prefix
        self.headless = headless
        self.timeout = timeout
        self.compliance_url = "https://www.openresponses.org/compliance"

    async def _fill_configuration(self, page: Page) -> None:
        """Fill in the test configuration form."""
        print("Filling configuration...")

        base_url_selector = 'input[placeholder*="Base URL"], input[name="baseUrl"], input[id="base-url"]'
        await page.fill(base_url_selector, self.base_url)

        model_selector = 'input[placeholder*="Model"], input[name="model"], input[id="model"]'
        await page.fill(model_selector, self.model)

        api_key_selector = (
            'input[type="password"], input[placeholder*="API Key"], input[name="apiKey"], input[id="api-key"]'
        )
        await page.fill(api_key_selector, self.api_key)

        auth_header_selector = 'input[placeholder*="Auth Header"], input[name="authHeader"], input[id="auth-header"]'
        try:
            await page.fill(auth_header_selector, self.auth_header_name)
        except PlaywrightTimeoutError:
            print("Warning: Could not find auth header field, using default")

        if self.use_bearer_prefix:
            bearer_checkbox_selector = 'input[type="checkbox"][name*="bearer"], input[type="checkbox"][id*="bearer"]'
            try:
                checkbox = page.locator(bearer_checkbox_selector).first
                if await checkbox.is_visible():
                    if not await checkbox.is_checked():
                        await checkbox.check()
            except PlaywrightTimeoutError:
                print("Warning: Could not find bearer prefix checkbox")

    async def _click_run_all_tests(self, page: Page) -> None:
        """Click the 'Run All Tests' button."""
        print("Clicking 'Run All Tests' button...")

        run_button_selectors = [
            'button:has-text("Run All Tests")',
            'button[type="button"]:has-text("Run All Tests")',
            "button.run-all-tests",
            "button#run-all-tests",
        ]

        for selector in run_button_selectors:
            try:
                button = page.locator(selector).first
                if await button.is_visible():
                    await button.click()
                    print(f"Clicked button using selector: {selector}")
                    return
            except PlaywrightTimeoutError:
                continue

        raise RuntimeError("Failed to find 'Run All Tests' button")

    async def _wait_for_tests_completion(self, page: Page) -> dict[str, Any]:
        """Wait for tests to complete and collect results."""
        print("Waiting for tests to complete...")

        results: dict[str, Any] = {
            "status": "unknown",
            "tests": [],
            "network_requests": [],
        }

        async def handle_request(request: Any) -> None:
            """Capture network requests for potential API reverse-engineering."""
            if request.url.startswith("http"):
                results["network_requests"].append(
                    {
                        "url": request.url,
                        "method": request.method,
                        "headers": await request.all_headers(),
                    }
                )

        page.on("request", handle_request)

        try:
            await page.wait_for_timeout(5000)

            test_results_selector = '.test-result, [class*="test"], [data-test-id]'
            test_elements = await page.locator(test_results_selector).all()

            for element in test_elements:
                test_name = await element.text_content() or "Unknown Test"
                is_passed = await element.evaluate(
                    "el => el.classList.contains('passed') || el.classList.contains('success') || el.getAttribute('data-status') === 'passed'"
                )
                is_failed = await element.evaluate(
                    "el => el.classList.contains('failed') || el.classList.contains('error') || el.getAttribute('data-status') === 'failed'"
                )

                status = "unknown"
                if is_passed:
                    status = "passed"
                elif is_failed:
                    status = "failed"

                results["tests"].append({"name": test_name.strip(), "status": status})

            passed_count = sum(1 for t in results["tests"] if t["status"] == "passed")
            failed_count = sum(1 for t in results["tests"] if t["status"] == "failed")
            total_count = len(results["tests"])

            if total_count > 0:
                if failed_count == 0:
                    results["status"] = "passed"
                else:
                    results["status"] = "failed"
                print(f"\nTest Results: {passed_count}/{total_count} passed, {failed_count} failed")
            else:
                print("\nWarning: Could not parse test results from page")

        except PlaywrightTimeoutError:
            print("Warning: Timeout waiting for test completion")

        return results

    async def run_tests(self) -> dict[str, Any]:
        """Run the compliance tests."""
        async with async_playwright() as p:
            print(f"Launching browser (headless={self.headless})...")
            browser = await p.chromium.launch(headless=self.headless)

            try:
                context = await browser.new_context()
                page = await context.new_page()

                print(f"Navigating to {self.compliance_url}...")
                await page.goto(self.compliance_url, wait_until="networkidle", timeout=30000)

                await self._fill_configuration(page)
                await asyncio.sleep(1)

                await self._click_run_all_tests(page)

                print("Waiting for tests to run...")
                await asyncio.sleep(10)

                results = await self._wait_for_tests_completion(page)

                if not self.headless:
                    print("\nBrowser will remain open for inspection. Press Enter to close...")
                    input()

                return results

            finally:
                await browser.close()

    async def inspect_network_calls(self) -> list[dict[str, Any]]:
        """Inspect network calls made during test execution to identify API endpoints."""
        print("Inspecting network calls...")
        network_calls: list[dict[str, Any]] = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                context = await browser.new_context()
                page = await context.new_page()

                async def handle_response(response: Any) -> None:
                    """Capture API responses."""
                    url = response.url
                    if any(keyword in url.lower() for keyword in ["api", "test", "run", "compliance", "acceptance"]):
                        try:
                            body = await response.body()
                            network_calls.append(
                                {
                                    "url": url,
                                    "method": response.request.method,
                                    "status": response.status,
                                    "headers": response.headers,
                                    "body": body.decode("utf-8", errors="ignore")[:1000],
                                }
                            )
                        except Exception as e:
                            print(f"Warning: Could not capture response body: {e}")

                page.on("response", handle_response)

                await page.goto(self.compliance_url, wait_until="networkidle", timeout=30000)
                await self._fill_configuration(page)
                await asyncio.sleep(1)
                await self._click_run_all_tests(page)
                await asyncio.sleep(15)

            finally:
                await browser.close()

        return network_calls


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Run Open Responses compliance tests programmatically",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("OPENRESPONSES_BASE_URL", ""),
        required=False,
        help="Base URL of the API to test (or set OPENRESPONSES_BASE_URL env var)",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("OPENRESPONSES_MODEL", ""),
        required=False,
        help="Model name to test (or set OPENRESPONSES_MODEL env var)",
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("OPENRESPONSES_API_KEY", ""),
        required=False,
        help="API key for authentication (or set OPENRESPONSES_API_KEY env var)",
    )
    parser.add_argument(
        "--auth-header-name",
        default=os.getenv("OPENRESPONSES_AUTH_HEADER", "Authorization"),
        help="Name of the authorization header (default: Authorization)",
    )
    parser.add_argument(
        "--use-bearer-prefix",
        action="store_true",
        default=os.getenv("OPENRESPONSES_USE_BEARER", "false").lower() == "true",
        help="Use Bearer prefix for API key",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        default=True,
        help="Run browser in headless mode (default: True)",
    )
    parser.add_argument(
        "--no-headless",
        action="store_false",
        dest="headless",
        help="Run browser with visible window",
    )
    parser.add_argument(
        "--inspect-network",
        action="store_true",
        help="Inspect network calls to identify API endpoints",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Save results to JSON file",
    )

    args = parser.parse_args()

    if not args.base_url:
        parser.error("--base-url is required (or set OPENRESPONSES_BASE_URL env var)")
    if not args.model:
        parser.error("--model is required (or set OPENRESPONSES_MODEL env var)")
    if not args.api_key:
        parser.error("--api-key is required (or set OPENRESPONSES_API_KEY env var)")

    runner = OpenResponsesTestRunner(
        base_url=args.base_url,
        model=args.model,
        api_key=args.api_key,
        auth_header_name=args.auth_header_name,
        use_bearer_prefix=args.use_bearer_prefix,
        headless=args.headless,
    )

    if args.inspect_network:
        print("Running in network inspection mode...")
        results = asyncio.run(runner.inspect_network_calls())
        print(f"\nFound {len(results)} relevant network calls:")
        for call in results:
            print(f"\n{call['method']} {call['url']}")
            print(f"  Status: {call['status']}")
            if call.get("body"):
                print(f"  Body preview: {call['body'][:200]}...")
    else:
        results = asyncio.run(runner.run_tests())

        print("\n" + "=" * 60)
        print("Test Summary")
        print("=" * 60)
        print(f"Status: {results.get('status', 'unknown')}")
        print(f"Tests found: {len(results.get('tests', []))}")
        for test in results.get("tests", []):
            status_icon = "✅" if test["status"] == "passed" else "❌" if test["status"] == "failed" else "⏳"
            print(f"  {status_icon} {test['name']}: {test['status']}")

        if results.get("network_requests"):
            print(f"\nNetwork requests captured: {len(results['network_requests'])}")

    if args.output:
        args.output.write_text(json.dumps(results, indent=2))
        print(f"\nResults saved to {args.output}")


if __name__ == "__main__":
    main()
