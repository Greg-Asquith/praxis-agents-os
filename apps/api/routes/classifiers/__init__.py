# apps/api/route/classifiers/__init__.py

"""Workspace classifier routes."""

from fastapi import APIRouter

from routes.classifiers.create_classifier import router as create_classifier_router
from routes.classifiers.delete_classifier import router as delete_classifier_router
from routes.classifiers.get_classifier import router as get_classifier_router
from routes.classifiers.list_classifiers import router as list_classifiers_router
from routes.classifiers.update_classifier import router as update_classifier_router

router = APIRouter(prefix="/classifiers", tags=["classifiers"])
router.include_router(list_classifiers_router)
router.include_router(create_classifier_router)
router.include_router(get_classifier_router)
router.include_router(update_classifier_router)
router.include_router(delete_classifier_router)
