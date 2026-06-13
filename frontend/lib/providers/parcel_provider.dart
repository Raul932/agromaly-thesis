import 'package:flutter/material.dart';
import '../models/parcel.dart';
import '../services/parcel_service.dart';

/// Provider managing the list of parcels and CRUD operations.
class ParcelProvider extends ChangeNotifier {
  final ParcelApiService _service = ParcelApiService();

  List<Parcel> _parcels = [];
  bool _isLoading = false;
  String? _error;

  List<Parcel> get parcels => _parcels;
  bool get isLoading => _isLoading;
  String? get error => _error;

  /// Fetch all parcels for the authenticated user.
  Future<void> loadParcels() async {
    _isLoading = true;
    _error = null;
    notifyListeners();

    try {
      _parcels = await _service.fetchParcels();
      _isLoading = false;
      notifyListeners();
    } catch (e) {
      _error = e.toString().replaceFirst('Exception: ', '');
      _isLoading = false;
      notifyListeners();
    }
  }

  /// Delete a parcel and remove it from the local list immediately.
  Future<bool> deleteParcel(String parcelId) async {
    try {
      await _service.deleteParcel(parcelId);
      _parcels = _parcels.where((p) => p.id != parcelId).toList();
      notifyListeners();
      return true;
    } catch (e) {
      _error = e.toString().replaceFirst('Exception: ', '');
      notifyListeners();
      return false;
    }
  }

  /// Update parcel metadata and reflect changes locally.
  Future<bool> updateParcel(
    String parcelId, {
    String? name,
    String? description,
    String? cropType,
  }) async {
    _error = null;
    try {
      final updated = await _service.updateParcel(
        parcelId,
        name: name,
        description: description,
        cropType: cropType,
      );
      _parcels = _parcels.map((p) => p.id == parcelId ? updated : p).toList();
      notifyListeners();
      return true;
    } catch (e) {
      _error = e.toString().replaceFirst('Exception: ', '');
      notifyListeners();
      return false;
    }
  }

  /// Create a new parcel and refresh the list.
  Future<bool> addParcel({
    required String name,
    required String cropType,
    required double areaHa,
    String? description,
    required List<List<List<double>>> coordinates,
  }) async {
    _isLoading = true;
    _error = null;
    notifyListeners();

    try {
      await _service.createParcel(
        name: name,
        cropType: cropType,
        areaHa: areaHa,
        description: description,
        coordinates: coordinates,
      );
      // Reload parcels from server to get the full response
      await loadParcels();
      return true;
    } catch (e) {
      _error = e.toString().replaceFirst('Exception: ', '');
      _isLoading = false;
      notifyListeners();
      return false;
    }
  }
}
