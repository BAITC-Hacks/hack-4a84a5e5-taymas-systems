from fastapi.testclient import TestClient


def test_business_constructor_creates_editable_card(tmp_path):
    from app import store as store_module
    from app.main import app

    store_module.reset_store(tmp_path / "store.json", "data/seed.json")
    client = TestClient(app)
    assert client.get("/business/new").status_code == 200

    questions = client.post("/business/new", data={"text": "A service is needed to process resident requests", "industry": "Other"})
    assert questions.status_code == 200
    assert "answer_0" in questions.text

    draft = list(store_module.get_store().drafts.values())[-1]
    response = client.post(f"/business/drafts/{draft.id}/answers", data={f"answer_{i}": f"Detailed answer {i}" for i, _ in enumerate(draft.questions)}, follow_redirects=False)
    assert response.status_code == 303
    editor = client.get(response.headers["location"])
    assert editor.status_code == 200
    assert "Preliminary rating" in editor.text

